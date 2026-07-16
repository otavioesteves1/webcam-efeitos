# -*- coding: utf-8 -*-
"""
Webcam Efeitos — painel unico com os tres mods de camera virtual:
  1. POKE-CAM    pokemons pixel-art passeando na tela
  2. MOLDURA-CAM seu rosto no buraco de uma moldura (cara no buraco)
  3. PIS-CAM     detector de piscada (bip + "PISCOU!" no video)

Abra o programa, clique em LIGAR e escolha "OBS Virtual Camera" no Discord.
Cada mod pode ser ativado/desativado a qualquer momento, e da pra combinar
os tres ao mesmo tempo.

Requisito: OBS Studio instalado (o driver de camera virtual vem com ele).

Modo de teste (sem interface): webcam_efeitos_app.py --teste [imagem.png]
"""

import os
import sys
import json
import time
import queue
import random
import threading
import urllib.request

os.environ["GLOG_minloglevel"] = "2"  # silencia avisos internos do MediaPipe

import cv2
import numpy as np
from PIL import Image, ImageSequence

try:
    import winsound
except ImportError:
    winsound = None

# ---------- pastas: dados do pacote vs dados do usuario ----------
if getattr(sys, "frozen", False):
    BASE = sys._MEIPASS                              # assets empacotados (so leitura)
    DADOS = os.path.dirname(sys.executable)          # ao lado do .exe (graváveis)
else:
    _raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    BASE = os.path.dirname(os.path.abspath(__file__))
    DADOS = BASE
    # no modo desenvolvimento, usa os assets dos projetos irmaos
    _ASSETS_DEV = {
        "molduras": os.path.join(_raiz, "03_MOLDURA-CAM", "molduras"),
        "sprites": os.path.join(_raiz, "02_GIF-WEBCAM", "sprites"),
        "modelo": os.path.join(_raiz, "01_PIS-CAM", "face_landmarker.task"),
    }

LARGURA, ALTURA, FPS = 1280, 720, 20
ARQ_CONFIG = os.path.join(DADOS, "config.json")
URL_SPRITES = "https://raw.githubusercontent.com/jakobhoeg/vscode-pokemon/main/media"
GERACOES = ["gen1", "gen2", "gen3", "gen4"]
URL_MODELO = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
              "face_landmarker/float16/1/face_landmarker.task")
EXT_IMG = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def pasta_molduras_pacote():
    if getattr(sys, "frozen", False):
        return os.path.join(BASE, "molduras")
    return _ASSETS_DEV["molduras"]


def pasta_sprites_pacote():
    if getattr(sys, "frozen", False):
        return os.path.join(BASE, "sprites")
    return _ASSETS_DEV["sprites"]


def caminho_modelo():
    if getattr(sys, "frozen", False):
        c = os.path.join(BASE, "face_landmarker.task")
        if os.path.exists(c):
            return c
    else:
        if os.path.exists(_ASSETS_DEV["modelo"]):
            return _ASSETS_DEV["modelo"]
    destino = os.path.join(DADOS, "face_landmarker.task")
    if not os.path.exists(destino):
        req = urllib.request.Request(URL_MODELO, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(destino, "wb") as f:
            f.write(r.read())
    return destino


def baixar_prioridade():
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000))
    except Exception:
        return False


# =====================  CONFIG COMPARTILHADA  =====================

PADRAO = {
    "geral": {"espelhar": True},
    "poke": {"ativo": True, "time": "pikachu 15\ncharmander 15"},
    "moldura": {"ativo": False, "nome": "gato-miau", "zoom": 0.85},
    "pisca": {"ativo": False, "limiar": 0.5, "bip": True, "contador": True},
}


class Config:
    """Dicionario com trava: a interface escreve, o pipeline le um retrato."""

    def __init__(self):
        self._lock = threading.Lock()
        self._dados = json.loads(json.dumps(PADRAO))
        self.versao_poke = 1  # muda quando o time de pokemons e alterado
        self.carregar()

    def carregar(self):
        try:
            with open(ARQ_CONFIG, encoding="utf-8") as f:
                salvo = json.load(f)
            with self._lock:
                for secao, valores in salvo.items():
                    if secao in self._dados and isinstance(valores, dict):
                        self._dados[secao].update(valores)
        except Exception:
            pass

    def salvar(self):
        try:
            with self._lock:
                copia = json.loads(json.dumps(self._dados))
            with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
                json.dump(copia, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def definir(self, secao, chave, valor):
        with self._lock:
            self._dados[secao][chave] = valor
        if (secao, chave) == ("poke", "time"):
            self.versao_poke += 1

    def retrato(self):
        with self._lock:
            return json.loads(json.dumps(self._dados))


# =====================  POKE-CAM  =====================

def baixar_arquivo(url, destino):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r, open(destino, "wb") as f:
        f.write(r.read())


def achar_sprite(nome, variante, anim):
    """Procura o gif no cache do usuario e nos empacotados; baixa se preciso."""
    arq = f"{nome}_{variante}_{anim}.gif"
    local = os.path.join(DADOS, "sprites", arq)
    if os.path.exists(local):
        return local
    empacotado = os.path.join(pasta_sprites_pacote(), arq)
    if os.path.exists(empacotado):
        return empacotado
    os.makedirs(os.path.dirname(local), exist_ok=True)
    ing = "walk" if anim == "walk" else "idle"
    for gen in GERACOES:
        try:
            baixar_arquivo(f"{URL_SPRITES}/{gen}/{nome}/{variante}_{ing}_8fps.gif", local)
            return local
        except Exception:
            continue
    if os.path.exists(local):
        os.remove(local)
    return None


def carregar_gif(caminho):
    im = Image.open(caminho)
    dur = im.info.get("duration") or 125
    frames = [np.array(f.convert("RGBA")) for f in ImageSequence.Iterator(im)]
    return frames, dur


def preparar_frame_sprite(rgba, fator):
    novo_w = max(1, round(rgba.shape[1] * fator))
    novo_h = max(1, round(rgba.shape[0] * fator))
    esc = cv2.resize(rgba, (novo_w, novo_h), interpolation=cv2.INTER_NEAREST)
    bgr = np.ascontiguousarray(esc[:, :, [2, 1, 0]])
    mascara = np.ascontiguousarray(np.where(esc[:, :, 3] > 127, 255, 0).astype(np.uint8))
    return bgr, mascara


def parse_time_pokemons(texto):
    lista = []
    for linha in texto.splitlines():
        linha = linha.strip().lower()
        if not linha or linha.startswith("#"):
            continue
        partes = linha.split()
        nome, variante, tamanho = partes[0], "default", 13
        for extra in partes[1:]:
            if extra == "shiny":
                variante = "shiny"
            elif extra.isdigit():
                tamanho = max(1, min(100, int(extra)))
        lista.append((nome, variante, tamanho))
    return lista


class Pokemon:
    def __init__(self, nome, anims_orig, tamanho):
        self.nome = nome
        alt_orig = anims_orig["anda"][0][0].shape[0]
        alvo = min(ALTURA * tamanho / 100.0, ALTURA - 8)
        fator = max(alvo / alt_orig, 0.05)
        self.anims = {}
        for estado, (frames, dur) in anims_orig.items():
            normais = [preparar_frame_sprite(f, fator) for f in frames]
            invertidos = [(np.ascontiguousarray(b[:, ::-1]), np.ascontiguousarray(m[:, ::-1]))
                          for b, m in normais]
            self.anims[estado] = (normais, invertidos, dur)
        self.y = max(0, ALTURA - self.anims["anda"][0][0][0].shape[0] - 8)
        self.limite_x = max(0, LARGURA - self.anims["anda"][0][0][0].shape[1])
        self.x = random.uniform(0, self.limite_x)
        self.direcao = random.choice([-1, 1])
        self.velocidade = random.uniform(60, 150)
        self.estado = "anda"
        self.timer = random.uniform(3, 8)
        self.nasceu = time.time()

    def atualizar(self, dt):
        self.timer -= dt
        if self.timer <= 0:
            if self.estado == "anda":
                self.estado, self.timer = "para", random.uniform(1.5, 4)
            else:
                self.estado, self.timer = "anda", random.uniform(3, 8)
                self.velocidade = random.uniform(60, 150)
                if random.random() < 0.3:
                    self.direcao *= -1
        if self.estado == "anda":
            self.x += self.direcao * self.velocidade * dt
            if self.x <= 0:
                self.x, self.direcao = 0, 1
            elif self.x >= self.limite_x:
                self.x, self.direcao = self.limite_x, -1

    def frame_atual(self):
        normais, invertidos, dur = self.anims[self.estado]
        idx = int((time.time() - self.nasceu) * 1000 / dur) % len(normais)
        return normais[idx] if self.direcao == 1 else invertidos[idx]


def desenhar_sprite(frame, bgr, mascara, x, y):
    fh, fw = frame.shape[:2]
    h, w = bgr.shape[:2]
    x, y = int(x), int(y)
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, fw), min(y + h, fh)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + w, y + h):
        bgr = np.ascontiguousarray(bgr[y0 - y:y1 - y, x0 - x:x1 - x])
        mascara = np.ascontiguousarray(mascara[y0 - y:y1 - y, x0 - x:x1 - x])
    roi = np.ascontiguousarray(frame[y0:y1, x0:x1])
    cv2.copyTo(bgr, mascara, roi)
    frame[y0:y1, x0:x1] = roi


def montar_time(texto, avisar):
    """Constroi a lista de objetos Pokemon a partir do texto do time."""
    cache = {}
    pokemons = []
    for nome, variante, tamanho in parse_time_pokemons(texto):
        chave = (nome, variante)
        if chave not in cache:
            anda = achar_sprite(nome, variante, "walk")
            para = achar_sprite(nome, variante, "idle")
            if not anda or not para:
                avisar(f"Pokemon '{nome}' nao encontrado (confira o nome em ingles)")
                cache[chave] = None
                continue
            cache[chave] = {"anda": carregar_gif(anda), "para": carregar_gif(para)}
        if cache[chave]:
            pokemons.append(Pokemon(nome, cache[chave], tamanho))
    return pokemons


# =====================  MOLDURA-CAM  =====================

def listar_molduras():
    """Molduras do pacote + as que o usuario colocar em molduras/ ao lado do exe.
    Retorna dict nome -> caminho (as do usuario tem prioridade)."""
    mapa = {}
    pastas = [pasta_molduras_pacote(), os.path.join(DADOS, "molduras")]
    if pastas[0] == pastas[1]:
        pastas = pastas[:1]
    for pasta in pastas:
        if not os.path.isdir(pasta):
            continue
        for f in sorted(os.listdir(pasta)):
            if f.lower().endswith(EXT_IMG):
                mapa[os.path.splitext(f)[0].lower()] = os.path.join(pasta, f)
    return mapa


def achar_buraco(img):
    h, w = img.shape[:2]
    faixas = [
        cv2.inRange(img, (248, 248, 248), (255, 255, 255)),
        cv2.inRange(img, (0, 0, 0), (10, 10, 10)),
    ]
    for mascara in faixas:
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidatos = []
        for c in contornos:
            x, y, bw, bh = cv2.boundingRect(c)
            area = cv2.contourArea(c)
            toca_borda = x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2
            if not toca_borda and 0.002 < area / (w * h) < 0.3 and len(c) >= 5:
                candidatos.append((area, c))
        if candidatos:
            melhor = max(candidatos, key=lambda t: t[0])[1]
            x, y, bw, bh = cv2.boundingRect(melhor)
            return x + bw / 2, y + bh / 2, bw, bh
    return None


def montar_cena(caminho):
    """Zoom na moldura ate cobrir a tela toda; devolve cena + buraco (ou None)."""
    img = cv2.imread(caminho)
    if img is None:
        return None
    buraco = achar_buraco(img)
    if buraco is None:
        return None
    cx, cy, ex, ey = buraco
    ih, iw = img.shape[:2]
    fator = max(LARGURA / iw, ALTURA / ih)
    novo_w, novo_h = round(iw * fator), round(ih * fator)
    grande = cv2.resize(img, (novo_w, novo_h),
                        interpolation=cv2.INTER_AREA if fator < 1 else cv2.INTER_LINEAR)
    hx, hy = cx * fator, cy * fator
    off_x = int(min(max(hx - LARGURA / 2, 0), novo_w - LARGURA))
    off_y = int(min(max(hy - ALTURA / 2, 0), novo_h - ALTURA))
    cena = np.ascontiguousarray(grande[off_y:off_y + ALTURA, off_x:off_x + LARGURA])
    return cena, (hx - off_x, hy - off_y, ex * fator, ey * fator)


def mascara_oval(larg, alt, feather=9):
    m = np.zeros((alt, larg), dtype=np.uint8)
    cv2.ellipse(m, (larg // 2, alt // 2), (larg // 2 - feather, alt // 2 - feather),
                0, 0, 360, 255, -1)
    m = cv2.GaussianBlur(m, (feather * 2 + 1, feather * 2 + 1), 0)
    return (m.astype(np.float32) / 255.0)[:, :, None]


FOLGA_TESTA = 0.15


def caixa_do_rosto(landmarks, w, h, aspecto, zoom):
    xs = [p.x for p in landmarks]
    ys = [p.y for p in landmarks]
    x0, x1 = min(xs) * w, max(xs) * w
    y0, y1 = min(ys) * h, max(ys) * h
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 - (y1 - y0) * FOLGA_TESTA / 2
    rw, rh = (x1 - x0) * zoom, (y1 - y0) * (zoom + FOLGA_TESTA)
    if rw / rh > aspecto:
        rh = rw / aspecto
    else:
        rw = rh * aspecto
    return cx, cy, rw, rh


class Moldura:
    """Cena da moldura pronta pra receber o rosto, com cache por (nome, zoom)."""

    def __init__(self, caminho):
        resultado = montar_cena(caminho)
        if resultado is None:
            raise ValueError("moldura sem buraco branco/preto detectavel")
        self.cena, (bx, by, bw, bh) = resultado
        self.px = max(0, int(bx - bw / 2) - 4)
        self.py = max(0, int(by - bh / 2) - 4)
        self.pw = min(int(bw) + 8, LARGURA - self.px)
        self.ph = min(int(bh) + 8, ALTURA - self.py)
        self.mascara = mascara_oval(self.pw, self.ph)
        self.fundo = self.cena[self.py:self.py + self.ph,
                               self.px:self.px + self.pw].astype(np.float32) * (1 - self.mascara)

    def compor(self, frame, caixa):
        saida = self.cena.copy()
        if caixa is not None:
            fh, fw = frame.shape[:2]
            cx, cy, rw, rh = caixa
            x0 = int(max(0, min(cx - rw / 2, fw - rw)))
            y0 = int(max(0, min(cy - rh / 2, fh - rh)))
            x1, y1 = int(min(x0 + rw, fw)), int(min(y0 + rh, fh))
            rosto = frame[y0:y1, x0:x1]
            if rosto.size:
                rosto = cv2.resize(rosto, (self.pw, self.ph), interpolation=cv2.INTER_LINEAR)
                patch = rosto.astype(np.float32) * self.mascara + self.fundo
                saida[self.py:self.py + self.ph,
                      self.px:self.px + self.pw] = patch.astype(np.uint8)
        return saida


# =====================  PIS-CAM  =====================

def tocar_bip():
    if winsound:
        threading.Thread(target=winsound.Beep, args=(900, 120), daemon=True).start()


def nivel_piscada(resultado):
    if not resultado.face_blendshapes:
        return None
    v = {b.category_name: b.score for b in resultado.face_blendshapes[0]}
    return (v.get("eyeBlinkLeft", 0) + v.get("eyeBlinkRight", 0)) / 2.0


def desenha_piscou(frame):
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 220, 255), 18)
    texto, fonte, escala = "PISCOU!", cv2.FONT_HERSHEY_TRIPLEX, 3.0
    (tw, th), _ = cv2.getTextSize(texto, fonte, escala, 6)
    x, y = (w - tw) // 2, (h + th) // 2
    cv2.putText(frame, texto, (x, y), fonte, escala, (0, 0, 0), 14, cv2.LINE_AA)
    cv2.putText(frame, texto, (x, y), fonte, escala, (0, 220, 255), 6, cv2.LINE_AA)


def desenha_contador(frame, n):
    cv2.putText(frame, f"piscadas: {n}", (20, 45),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.putText(frame, f"piscadas: {n}", (20, 45),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)


# =====================  PIPELINE  =====================

class Pipeline(threading.Thread):
    """Thread que le a webcam, aplica os mods ativos e alimenta a camera virtual."""

    def __init__(self, config, status):
        super().__init__(daemon=True)
        self.config = config
        self.status = status  # queue.Queue de mensagens pra interface
        self.parar = threading.Event()

    def avisar(self, msg):
        self.status.put(msg)

    def run(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            FaceLandmarker, FaceLandmarkerOptions, RunningMode,
        )
        import pyvirtualcam

        cap = landmarker = cam_virtual = None
        try:
            self.avisar("Abrindo a webcam...")
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
            cap.set(cv2.CAP_PROP_FPS, FPS)
            ok, frame = cap.read() if cap.isOpened() else (False, None)
            if not ok:
                self.avisar("ERRO: webcam ocupada ou nao encontrada. Feche outros programas que usem a camera.")
                return

            self.avisar("Carregando o detector de rosto...")
            landmarker = FaceLandmarker.create_from_options(FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=caminho_modelo()),
                running_mode=RunningMode.VIDEO,
                num_faces=1,
                output_face_blendshapes=True,
            ))

            try:
                cam_virtual = pyvirtualcam.Camera(width=LARGURA, height=ALTURA, fps=FPS,
                                                  fmt=pyvirtualcam.PixelFormat.BGR)
            except Exception:
                self.avisar("ERRO: camera virtual indisponivel. O OBS Studio esta instalado? (obsproject.com)")
                return

            self.avisar(f"LIGADO! No Discord escolha '{cam_virtual.device}'.")

            pokemons, versao_poke = [], 0
            moldura, chave_moldura = None, None
            caixa = None
            olho_fechado, piscadas, efeito_ate = False, 0, 0.0
            inicio = time.time()
            anterior = time.time()

            while not self.parar.is_set():
                cfg = self.config.retrato()

                # (re)montar time de pokemons se o texto mudou
                if cfg["poke"]["ativo"] and versao_poke != self.config.versao_poke:
                    versao_poke = self.config.versao_poke
                    self.avisar("Montando o time de pokemons...")
                    pokemons = montar_time(cfg["poke"]["time"], self.avisar)
                    self.avisar(f"Time pronto: {len(pokemons)} pokemon(s).")

                # (re)montar moldura se nome/zoom mudou
                if cfg["moldura"]["ativo"]:
                    chave = cfg["moldura"]["nome"]
                    if chave != chave_moldura:
                        chave_moldura = chave
                        caminho = listar_molduras().get(chave)
                        try:
                            moldura = Moldura(caminho) if caminho else None
                        except ValueError:
                            moldura = None
                        if moldura is None:
                            self.avisar(f"Moldura '{chave}' invalida ou sem buraco.")

                ok, frame = cap.read()
                if not ok:
                    continue
                if cfg["geral"]["espelhar"]:
                    frame = cv2.flip(frame, 1)
                fh, fw = frame.shape[:2]

                agora = time.time()
                dt = min(agora - anterior, 0.1)
                anterior = agora

                usa_rosto = cfg["pisca"]["ativo"] or (cfg["moldura"]["ativo"] and moldura)
                resultado = None
                if usa_rosto:
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB,
                                      data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    resultado = landmarker.detect_for_video(mp_img, int((agora - inicio) * 1000))

                # MOLDURA-CAM
                if cfg["moldura"]["ativo"] and moldura:
                    if resultado and resultado.face_landmarks:
                        nova = caixa_do_rosto(resultado.face_landmarks[0], fw, fh,
                                              moldura.pw / moldura.ph, cfg["moldura"]["zoom"])
                        caixa = nova if caixa is None else tuple(
                            0.25 * n + 0.75 * v for n, v in zip(nova, caixa))
                    saida = moldura.compor(frame, caixa)
                else:
                    saida = frame

                # POKE-CAM
                if cfg["poke"]["ativo"]:
                    for p in pokemons:
                        p.atualizar(dt)
                        bgr, masc = p.frame_atual()
                        desenhar_sprite(saida, bgr, masc, p.x, p.y)

                # PIS-CAM
                if cfg["pisca"]["ativo"]:
                    nivel = nivel_piscada(resultado) if resultado else None
                    if nivel is not None:
                        if nivel > cfg["pisca"]["limiar"] and not olho_fechado:
                            olho_fechado = True
                        elif nivel <= cfg["pisca"]["limiar"] and olho_fechado:
                            olho_fechado = False
                            piscadas += 1
                            efeito_ate = time.time() + 0.7
                            if cfg["pisca"]["bip"]:
                                tocar_bip()
                    if time.time() < efeito_ate:
                        desenha_piscou(saida)
                    if cfg["pisca"]["contador"]:
                        desenha_contador(saida, piscadas)

                cam_virtual.send(saida)
                cam_virtual.sleep_until_next_frame()

            self.avisar("Desligado.")
        except Exception as e:
            self.avisar(f"ERRO inesperado: {e}")
        finally:
            if cap is not None:
                cap.release()
            if cam_virtual is not None:
                cam_virtual.close()
            if landmarker is not None:
                landmarker.close()


# =====================  INTERFACE  =====================

def interface():
    import tkinter as tk
    from tkinter import ttk

    config = Config()
    status = queue.Queue()
    pipeline = [None]

    raiz = tk.Tk()
    raiz.title("Webcam Efeitos")
    raiz.resizable(False, False)

    estilo = ttk.Style(raiz)
    try:
        estilo.theme_use("vista")
    except Exception:
        pass

    quadro = ttk.Frame(raiz, padding=14)
    quadro.grid(sticky="nsew")

    # ---- botao liga/desliga + status ----
    var_botao = tk.StringVar(value="▶  LIGAR CAMERA VIRTUAL")
    var_status = tk.StringVar(value="Pronto. Clique em LIGAR e escolha 'OBS Virtual Camera' no Discord.")

    def alternar():
        if pipeline[0] and pipeline[0].is_alive():
            pipeline[0].parar.set()
            var_botao.set("▶  LIGAR CAMERA VIRTUAL")
        else:
            pipeline[0] = Pipeline(config, status)
            pipeline[0].start()
            var_botao.set("⏹  DESLIGAR")

    botao = ttk.Button(quadro, textvariable=var_botao, command=alternar)
    botao.grid(row=0, column=0, columnspan=2, sticky="ew", ipady=8)
    rotulo_status = ttk.Label(quadro, textvariable=var_status, wraplength=460,
                              foreground="#555")
    rotulo_status.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 12))

    def fazer_check(pai, texto, secao, chave, linha):
        var = tk.BooleanVar(value=config.retrato()[secao][chave])
        ttk.Checkbutton(pai, text=texto, variable=var,
                        command=lambda: config.definir(secao, chave, var.get())
                        ).grid(row=linha, column=0, columnspan=2, sticky="w")
        return var

    # ---- POKE-CAM ----
    fr_poke = ttk.LabelFrame(quadro, text=" 🐛 POKE-CAM — pokemons na tela ", padding=10)
    fr_poke.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
    fazer_check(fr_poke, "Ativar", "poke", "ativo", 0)
    ttk.Label(fr_poke, text="Time (um por linha: nome [tamanho 1-100] [shiny]):",
              foreground="#555").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 2))
    texto_time = tk.Text(fr_poke, width=44, height=4, font=("Consolas", 10))
    texto_time.insert("1.0", config.retrato()["poke"]["time"])
    texto_time.grid(row=2, column=0, sticky="ew")

    def aplicar_time():
        config.definir("poke", "time", texto_time.get("1.0", "end").strip())
        config.salvar()

    ttk.Button(fr_poke, text="Aplicar\ntime", command=aplicar_time).grid(
        row=2, column=1, sticky="ns", padx=(6, 0))

    # ---- MOLDURA-CAM ----
    fr_mold = ttk.LabelFrame(quadro, text=" 🖼 MOLDURA-CAM — cara no buraco ", padding=10)
    fr_mold.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
    fazer_check(fr_mold, "Ativar", "moldura", "ativo", 0)
    ttk.Label(fr_mold, text="Moldura:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    nomes = sorted(listar_molduras())
    var_moldura = tk.StringVar(value=config.retrato()["moldura"]["nome"])
    combo = ttk.Combobox(fr_mold, textvariable=var_moldura, values=nomes,
                         state="readonly", width=24)
    combo.grid(row=1, column=1, sticky="w", pady=(6, 0), padx=(6, 0))
    combo.bind("<<ComboboxSelected>>",
               lambda e: (config.definir("moldura", "nome", var_moldura.get()), config.salvar()))
    ttk.Label(fr_mold, text="Zoom do rosto (esq = mais zoom):").grid(
        row=2, column=0, sticky="w", pady=(6, 0))
    var_zoom = tk.DoubleVar(value=config.retrato()["moldura"]["zoom"])
    ttk.Scale(fr_mold, from_=0.6, to=1.5, variable=var_zoom,
              command=lambda v: config.definir("moldura", "zoom", round(float(v), 2))
              ).grid(row=2, column=1, sticky="ew", pady=(6, 0), padx=(6, 0))
    ttk.Label(fr_mold, foreground="#888",
              text="Suas molduras: crie uma pasta 'molduras' ao lado do programa").grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

    # ---- PIS-CAM ----
    fr_pisca = ttk.LabelFrame(quadro, text=" 👁 PIS-CAM — detector de piscada ", padding=10)
    fr_pisca.grid(row=4, column=0, columnspan=2, sticky="ew", pady=4)
    fazer_check(fr_pisca, "Ativar", "pisca", "ativo", 0)
    ttk.Label(fr_pisca, text="Sensibilidade (esq = detecta mais facil):").grid(
        row=1, column=0, sticky="w", pady=(6, 0))
    var_limiar = tk.DoubleVar(value=config.retrato()["pisca"]["limiar"])
    ttk.Scale(fr_pisca, from_=0.3, to=0.7, variable=var_limiar,
              command=lambda v: config.definir("pisca", "limiar", round(float(v), 2))
              ).grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(6, 0))
    fazer_check(fr_pisca, "Tocar bip ao piscar (so voce ouve)", "pisca", "bip", 2)
    fazer_check(fr_pisca, "Mostrar contador de piscadas", "pisca", "contador", 3)

    # ---- geral ----
    fr_geral = ttk.Frame(quadro, padding=(0, 6))
    fr_geral.grid(row=5, column=0, columnspan=2, sticky="ew")
    fazer_check(fr_geral, "Espelhar video (como um espelho)", "geral", "espelhar", 0)

    for fr in (fr_poke, fr_mold, fr_pisca):
        fr.columnconfigure(1, weight=1)
    quadro.columnconfigure(0, weight=1)

    def ciclo_status():
        try:
            while True:
                var_status.set(status.get_nowait())
        except queue.Empty:
            pass
        if pipeline[0] and not pipeline[0].is_alive() and var_botao.get().startswith("⏹"):
            var_botao.set("▶  LIGAR CAMERA VIRTUAL")
        raiz.after(200, ciclo_status)

    def ao_fechar():
        config.salvar()
        if pipeline[0] and pipeline[0].is_alive():
            pipeline[0].parar.set()
            pipeline[0].join(timeout=3)
        raiz.destroy()

    raiz.protocol("WM_DELETE_WINDOW", ao_fechar)
    ciclo_status()
    raiz.mainloop()


# =====================  MODO TESTE (sem interface)  =====================

def modo_teste(caminho_frame=None):
    """Compoe um unico frame com os tres mods ligados e salva teste_app.png."""
    saida_arq = os.path.join(DADOS, "teste_app.png")
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (
        FaceLandmarker, FaceLandmarkerOptions, RunningMode,
    )

    if caminho_frame and os.path.exists(caminho_frame):
        frame = cv2.imread(caminho_frame)
        frame = cv2.resize(frame, (LARGURA, ALTURA))
    else:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            print("TESTE FALHOU: sem webcam e sem imagem de teste")
            return 1

    landmarker = FaceLandmarker.create_from_options(FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=caminho_modelo()),
        running_mode=RunningMode.VIDEO, num_faces=1,
        output_face_blendshapes=True))
    resultado = landmarker.detect_for_video(
        mp.Image(image_format=mp.ImageFormat.SRGB,
                 data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), 0)
    landmarker.close()

    molduras = listar_molduras()
    nome = "gato-miau" if "gato-miau" in molduras else (sorted(molduras)[0] if molduras else None)
    if nome is None:
        print("TESTE FALHOU: nenhuma moldura encontrada")
        return 1
    moldura = Moldura(molduras[nome])
    caixa = None
    if resultado.face_landmarks:
        caixa = caixa_do_rosto(resultado.face_landmarks[0], frame.shape[1], frame.shape[0],
                               moldura.pw / moldura.ph, 0.85)
    saida = moldura.compor(frame, caixa)

    pokemons = montar_time("pikachu 15\ncharmander 20", print)
    for i, p in enumerate(pokemons):
        p.x = 150 + i * 300
        bgr, masc = p.frame_atual()
        desenhar_sprite(saida, bgr, masc, p.x, p.y)

    desenha_piscou(saida)
    desenha_contador(saida, 42)

    cv2.imwrite(saida_arq, saida)
    print(f"TESTE OK: moldura '{nome}', {len(pokemons)} pokemons, rosto "
          f"{'detectado' if caixa else 'NAO detectado'} -> {saida_arq}")
    return 0


if __name__ == "__main__":
    baixar_prioridade()
    if "--teste" in sys.argv:
        idx = sys.argv.index("--teste")
        arg = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else None
        sys.exit(modo_teste(arg))
    interface()
