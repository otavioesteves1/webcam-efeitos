# -*- coding: utf-8 -*-
"""
GifCam — pokemons andando na sua webcam (estilo vscode-pokemon)
Le a webcam real, desenha os pokemons passeando na parte de baixo do video
e manda tudo pra camera virtual que o Discord enxerga.

Escolha os pokemons no arquivo pokemons.txt (um por linha, pode repetir).
Depois do nome, pode colocar:
  - um numero de 1 a 100 = tamanho (% da altura da tela). ex: "pikachu 30"
  - a palavra shiny = versao shiny. ex: "pikachu 30 shiny"
Sprites do projeto open-source vscode-pokemon (github.com/jakobhoeg/vscode-pokemon),
baixados na primeira vez e guardados na pasta sprites/.

Feito pra nao pesar no PC enquanto voce joga:
  - roda com prioridade baixa (o jogo sempre vem primeiro na fila da CPU)
  - a transparencia e pre-calculada uma unica vez, nada de conta pesada por frame
  - 20 fps por padrao (suave no Discord e mais leve; suba pra 30 se quiser)

Pra rodar:    python gif_cam.py   (ou duplo clique no GifCam.bat)
Pra encerrar: Ctrl+C no terminal.
"""

import os
import sys
import time
import random
import urllib.request

import cv2
import numpy as np
import pyvirtualcam
from PIL import Image, ImageSequence

# ---------- Ajustes (mexa a vontade) ----------
LARGURA, ALTURA = 1280, 720  # diminua pra 960x540 se quiser mais leve ainda
FPS = 20                     # 20 e suave no Discord; 30 fica mais fluido e pesa um pouco mais

TAMANHO_PADRAO = 13  # tamanho de quem nao tem numero no pokemons.txt (% da altura)
MARGEM_BAIXO = 8     # distancia da borda de baixo do video (px)
VEL_MIN, VEL_MAX = 60, 150   # velocidade de caminhada (px por segundo)
ESPELHAR = False     # True = video espelhado (como um espelho)
PRIORIDADE_BAIXA = True      # True = o Windows da CPU pro jogo antes do GifCam
# ----------------------------------------------

PASTA = os.path.dirname(os.path.abspath(__file__))
PASTA_SPRITES = os.path.join(PASTA, "sprites")
ARQ_POKEMONS = os.path.join(PASTA, "pokemons.txt")
URL_BASE = "https://raw.githubusercontent.com/jakobhoeg/vscode-pokemon/main/media"
GERACOES = ["gen1", "gen2", "gen3", "gen4"]


def baixar_prioridade():
    """Marca o processo como 'menos importante' pro Windows: se o jogo precisar
    de CPU, ele passa na frente do GifCam sem pensar duas vezes."""
    try:
        import ctypes
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        k32 = ctypes.windll.kernel32
        # tipos explicitos: sem isso o handle de 64 bits e truncado e a chamada falha
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(),
                                         BELOW_NORMAL_PRIORITY_CLASS))
    except Exception:
        return False


def baixar(url, destino):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r, open(destino, "wb") as f:
        f.write(r.read())


def garantir_sprites(nome, variante):
    """Baixa os gifs de andar/parar do pokemon se ainda nao estiverem na pasta.
    Retorna (caminho_anda, caminho_para) ou None se o pokemon nao existir."""
    os.makedirs(PASTA_SPRITES, exist_ok=True)
    anda = os.path.join(PASTA_SPRITES, f"{nome}_{variante}_walk.gif")
    para = os.path.join(PASTA_SPRITES, f"{nome}_{variante}_idle.gif")
    if os.path.exists(anda) and os.path.exists(para):
        return anda, para
    for gen in GERACOES:
        try:
            print(f"  baixando {nome} ({variante}, {gen})...", end=" ", flush=True)
            baixar(f"{URL_BASE}/{gen}/{nome}/{variante}_walk_8fps.gif", anda)
            baixar(f"{URL_BASE}/{gen}/{nome}/{variante}_idle_8fps.gif", para)
            print("ok!")
            return anda, para
        except Exception:
            print("nao e dessa geracao...")
    for arq in (anda, para):
        if os.path.exists(arq):
            os.remove(arq)
    return None


def carregar_anim(caminho):
    """Le um gif e devolve (frames RGBA no tamanho original, duracao_ms)."""
    im = Image.open(caminho)
    dur = im.info.get("duration") or 125
    frames = [np.array(f.convert("RGBA")) for f in ImageSequence.Iterator(im)]
    return frames, dur


def preparar_frame(rgba, fator):
    """Transforma um frame RGBA em (bgr, mascara) ja escalado, pronto pra
    colar no video sem nenhuma conta de transparencia na hora."""
    novo_w = max(1, round(rgba.shape[1] * fator))
    novo_h = max(1, round(rgba.shape[0] * fator))
    esc = cv2.resize(rgba, (novo_w, novo_h), interpolation=cv2.INTER_NEAREST)
    bgr = np.ascontiguousarray(esc[:, :, [2, 1, 0]])
    mascara = np.ascontiguousarray(np.where(esc[:, :, 3] > 127, 255, 0).astype(np.uint8))
    return bgr, mascara


class Pokemon:
    """Um pokemon passeando: anda um tempo, para um tempo, vira nas bordas.
    tamanho = altura do sprite em % da altura da tela (1 a 100)."""

    def __init__(self, nome, anims_orig, largura_tela, altura_tela, tamanho):
        self.nome = nome
        alt_orig = anims_orig["anda"][0][0].shape[0]
        alvo = altura_tela * max(1, min(100, tamanho)) / 100.0
        alvo = min(alvo, altura_tela - MARGEM_BAIXO)  # nao passa do teto
        fator = max(alvo / alt_orig, 0.05)

        # pre-calcula TODOS os frames (normal e espelhado) uma unica vez
        self.anims = {}
        for estado, (frames, dur) in anims_orig.items():
            normais = [preparar_frame(f, fator) for f in frames]
            invertidos = [(np.ascontiguousarray(b[:, ::-1]), np.ascontiguousarray(m[:, ::-1]))
                          for b, m in normais]
            self.anims[estado] = (normais, invertidos, dur)

        alt_sprite = self.anims["anda"][0][0][0].shape[0]
        larg_sprite = self.anims["anda"][0][0][0].shape[1]
        self.y = max(0, altura_tela - alt_sprite - MARGEM_BAIXO)
        self.limite_x = max(0, largura_tela - larg_sprite)
        self.x = random.uniform(0, self.limite_x)
        self.direcao = random.choice([-1, 1])
        self.velocidade = random.uniform(VEL_MIN, VEL_MAX)
        self.estado = "anda"
        self.timer = random.uniform(3, 8)
        self.nasceu = time.time()

    def atualizar(self, dt):
        self.timer -= dt
        if self.timer <= 0:
            if self.estado == "anda":
                self.estado = "para"
                self.timer = random.uniform(1.5, 4)
            else:
                self.estado = "anda"
                self.timer = random.uniform(3, 8)
                self.velocidade = random.uniform(VEL_MIN, VEL_MAX)
                if random.random() < 0.3:
                    self.direcao *= -1
        if self.estado == "anda":
            self.x += self.direcao * self.velocidade * dt
            if self.x <= 0:
                self.x, self.direcao = 0, 1
            elif self.x >= self.limite_x:
                self.x, self.direcao = self.limite_x, -1

    def frame_atual(self):
        """Retorna (bgr, mascara) do frame de animacao da vez."""
        normais, invertidos, dur = self.anims[self.estado]
        idx = int((time.time() - self.nasceu) * 1000 / dur) % len(normais)
        # sprite original olha pra direita; andando pra esquerda, espelha
        return normais[idx] if self.direcao == 1 else invertidos[idx]


def desenhar(frame, bgr, mascara, x, y):
    """Cola o sprite no frame usando a mascara pre-calculada (rapido, em C),
    cortando o que sair das bordas."""
    fh, fw = frame.shape[:2]
    h, w = bgr.shape[:2]
    x, y = int(x), int(y)
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, fw), min(y + h, fh)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + w, y + h):  # saiu da tela: recorta
        bgr = np.ascontiguousarray(bgr[y0 - y:y1 - y, x0 - x:x1 - x])
        mascara = np.ascontiguousarray(mascara[y0 - y:y1 - y, x0 - x:x1 - x])
    roi = np.ascontiguousarray(frame[y0:y1, x0:x1])
    cv2.copyTo(bgr, mascara, roi)
    frame[y0:y1, x0:x1] = roi


def ler_lista_pokemons():
    """Le o pokemons.txt. Cada linha: nome [tamanho 1-100] [shiny], em qualquer ordem.
    Retorna lista de (nome, variante, tamanho)."""
    if not os.path.exists(ARQ_POKEMONS):
        with open(ARQ_POKEMONS, "w", encoding="utf-8") as f:
            f.write("# Um pokemon por linha (pode repetir o mesmo varias vezes).\n")
            f.write("# Depois do nome: numero 1-100 = tamanho (% da altura da tela),\n")
            f.write("# e/ou a palavra shiny. Ex: pikachu 30 shiny\n")
            f.write("pikachu 15\n")
        print(f"Criei o arquivo {os.path.basename(ARQ_POKEMONS)} com um pikachu de exemplo.")
    lista = []
    with open(ARQ_POKEMONS, encoding="utf-8") as f:
        for num_linha, linha in enumerate(f, start=1):
            linha = linha.strip().lower()
            if not linha or linha.startswith("#"):
                continue
            partes = linha.split()
            nome = partes[0]
            variante = "default"
            tamanho = TAMANHO_PADRAO
            for extra in partes[1:]:
                if extra == "shiny":
                    variante = "shiny"
                elif extra.isdigit():
                    tamanho = max(1, min(100, int(extra)))
                else:
                    print(f"  AVISO: nao entendi '{extra}' na linha {num_linha} (ignorei).")
            lista.append((nome, variante, tamanho))
    return lista


def main():
    if PRIORIDADE_BAIXA and baixar_prioridade():
        print("Prioridade baixa ativada: seu jogo vem primeiro.")

    escolhidos = ler_lista_pokemons()
    if not escolhidos:
        print("ERRO: o pokemons.txt esta vazio. Escreva um pokemon por linha e rode de novo.")
        sys.exit(1)

    print("Preparando os pokemons...")
    cache_anims = {}
    time_do_usuario = []
    for nome, variante, tamanho in escolhidos:
        chave = (nome, variante)
        if chave not in cache_anims:
            caminhos = garantir_sprites(nome, variante)
            if caminhos is None:
                print(f"  AVISO: nao achei '{nome}' em nenhuma geracao (gen1-gen4). Confira o nome (em ingles, ex: charizard).")
                cache_anims[chave] = None
                continue
            cache_anims[chave] = {
                "anda": carregar_anim(caminhos[0]),
                "para": carregar_anim(caminhos[1]),
            }
        if cache_anims[chave] is not None:
            time_do_usuario.append((nome, variante, tamanho))

    if not time_do_usuario:
        print("ERRO: nenhum pokemon valido na lista. Nada pra mostrar.")
        sys.exit(1)

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    ok, frame = cap.read() if cap.isOpened() else (False, None)
    if not ok:
        print("ERRO: nao consegui abrir a webcam.")
        print("Feche outros programas que estejam usando a camera (Discord, OBS, PiscaCam) e tente de novo.")
        sys.exit(1)
    h, w = frame.shape[:2]

    pokemons = [Pokemon(nome, cache_anims[(nome, var)], w, h, tam)
                for nome, var, tam in time_do_usuario]

    try:
        cam_virtual = pyvirtualcam.Camera(width=w, height=h, fps=FPS,
                                          fmt=pyvirtualcam.PixelFormat.BGR)
    except Exception as e:
        print("ERRO: nao consegui criar a camera virtual.")
        print("Confira se o OBS esta instalado e se nada mais esta usando a camera virtual (PiscaCam, OBS).")
        print(f"Detalhe tecnico: {e}")
        sys.exit(1)

    nomes = ", ".join(p.nome for p in pokemons)
    print(f"\nGifCam rodando com {len(pokemons)} pokemon(s): {nomes}")
    print(f"Camera virtual: {cam_virtual.device} ({w}x{h} @ {FPS}fps)")
    print("No Discord, selecione essa camera em Voz e Video. Ctrl+C para sair.")

    anterior = time.time()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            if ESPELHAR:
                frame = cv2.flip(frame, 1)

            agora = time.time()
            dt = min(agora - anterior, 0.1)
            anterior = agora

            for p in pokemons:
                p.atualizar(dt)
                bgr, mascara = p.frame_atual()
                desenhar(frame, bgr, mascara, p.x, p.y)

            cam_virtual.send(frame)
            cam_virtual.sleep_until_next_frame()
    except KeyboardInterrupt:
        print("\nEncerrando. Ate a proxima!")
    finally:
        cap.release()
        cam_virtual.close()


if __name__ == "__main__":
    main()
