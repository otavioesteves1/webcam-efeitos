# -*- coding: utf-8 -*-
"""
MolduraCam — seu rosto dentro de uma moldura (tipo "cara no buraco" de parque)
A camera acha seu rosto, recorta so ele e encaixa no buraco branco da moldura.
Seu corpo e o fundo somem: o que vai pro Discord e a moldura com sua cara.

As molduras ficam na pasta molduras/ e voce escolhe qual usar escrevendo o nome
dela no moldura.txt. Qualquer imagem com um buraco BRANCO (ou preto) oval/redondo
funciona — o programa acha o buraco sozinho.

No Discord: Configuracoes > Voz e video > Camera > "OBS Virtual Camera"

Pra rodar:    python moldura_cam.py   (ou duplo clique no MolduraCam.bat)
Pra encerrar: Ctrl+C no terminal.
"""

import os
import sys
import time
import urllib.request

import cv2
import numpy as np
import pyvirtualcam
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker, FaceLandmarkerOptions, RunningMode,
)

# ---------- Ajustes (mexa a vontade) ----------
LARGURA, ALTURA, FPS = 1280, 720, 20

FOLGA_ROSTO = 1.25    # quanto do entorno do rosto entra no recorte (1.0 = so o rosto)
FOLGA_TESTA = 0.15    # extra pra cima, pra testa nao ficar cortada (% da altura do rosto)
SUAVIZACAO = 0.25     # 0.1 = movimento bem macio / 1.0 = cola no rosto sem suavizar
ESPELHAR = True       # True = como espelho (voce se reconhece melhor)
PRIORIDADE_BAIXA = True  # o Windows da CPU pro jogo antes do MolduraCam
# ----------------------------------------------

PASTA = os.path.dirname(os.path.abspath(__file__))
PASTA_MOLDURAS = os.path.join(PASTA, "molduras")
ARQ_ESCOLHA = os.path.join(PASTA, "moldura.txt")
EXTENSOES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
URL_MODELO = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
              "face_landmarker/float16/1/face_landmarker.task")


def baixar_prioridade():
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000))
    except Exception:
        return False


def achar_modelo():
    """Procura o face_landmarker.task aqui e no 01_PIS-CAM; baixa se nao achar."""
    candidatos = [
        os.path.join(PASTA, "face_landmarker.task"),
        os.path.join(os.path.dirname(PASTA), "01_PIS-CAM", "face_landmarker.task"),
    ]
    for c in candidatos:
        if os.path.exists(c):
            return c
    destino = candidatos[0]
    print("Baixando o modelo de deteccao de rosto (3.7MB, so na primeira vez)...")
    req = urllib.request.Request(URL_MODELO, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(destino, "wb") as f:
        f.write(r.read())
    return destino


def achar_buraco(img):
    """Acha o buraco da moldura: o maior blob branco (ou preto) que nao encosta
    na borda da imagem. Retorna (cx, cy, larg, alt) da elipse, ou None."""
    h, w = img.shape[:2]
    faixas = [
        cv2.inRange(img, (248, 248, 248), (255, 255, 255)),  # buraco branco
        cv2.inRange(img, (0, 0, 0), (10, 10, 10)),           # buraco preto
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


def listar_molduras():
    os.makedirs(PASTA_MOLDURAS, exist_ok=True)
    return sorted(f for f in os.listdir(PASTA_MOLDURAS)
                  if f.lower().endswith(EXTENSOES))


def escolher_moldura():
    """Le o moldura.txt e devolve o caminho da moldura escolhida."""
    disponiveis = listar_molduras()
    if not disponiveis:
        print(f"ERRO: nenhuma imagem na pasta {os.path.basename(PASTA_MOLDURAS)}/.")
        print("Coloque imagens de moldura (com buraco branco ou preto) la dentro.")
        sys.exit(1)

    if not os.path.exists(ARQ_ESCOLHA):
        padrao = os.path.splitext(disponiveis[0])[0]
        with open(ARQ_ESCOLHA, "w", encoding="utf-8") as f:
            f.write("# Escreva o nome da moldura que quer usar (uma so).\n")
            f.write("# Disponiveis: " + ", ".join(os.path.splitext(d)[0] for d in disponiveis) + "\n")
            f.write(padrao + "\n")
        print(f"Criei o moldura.txt com a moldura '{padrao}'.")

    escolha = ""
    with open(ARQ_ESCOLHA, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip().lower()
            if linha and not linha.startswith("#"):
                escolha = linha
                break

    for arq in disponiveis:
        if arq.lower() == escolha or os.path.splitext(arq)[0].lower() == escolha:
            print(f"Moldura escolhida: {os.path.splitext(arq)[0]}")
            return os.path.join(PASTA_MOLDURAS, arq)

    print(f"ERRO: nao achei a moldura '{escolha}' na pasta molduras/.")
    print("Disponiveis: " + ", ".join(os.path.splitext(d)[0] for d in disponiveis))
    sys.exit(1)


def montar_cena(caminho_moldura, largura, altura):
    """Monta o quadro base: moldura centralizada no tamanho do video, e devolve
    tambem a posicao/tamanho do buraco ja em coordenadas do video."""
    img = cv2.imread(caminho_moldura)
    if img is None:
        print(f"ERRO: nao consegui abrir {os.path.basename(caminho_moldura)}.")
        sys.exit(1)

    buraco = achar_buraco(img)
    if buraco is None:
        print("ERRO: nao achei um buraco branco (nem preto) nessa moldura.")
        print("O buraco precisa ser branco ou preto puro e nao encostar nas bordas da imagem.")
        sys.exit(1)
    cx, cy, ex, ey = buraco

    ih, iw = img.shape[:2]
    fator = min(largura / iw, altura / ih)
    novo_w, novo_h = round(iw * fator), round(ih * fator)
    off_x, off_y = (largura - novo_w) // 2, (altura - novo_h) // 2

    cor_fundo = img[2, 2].tolist()  # cor do canto da imagem preenche as laterais
    cena = np.full((altura, largura, 3), cor_fundo, dtype=np.uint8)
    cena[off_y:off_y + novo_h, off_x:off_x + novo_w] = cv2.resize(
        img, (novo_w, novo_h), interpolation=cv2.INTER_AREA)

    return cena, (cx * fator + off_x, cy * fator + off_y, ex * fator, ey * fator)


def mascara_oval(larg, alt, feather=9):
    """Mascara 0..1 em forma de elipse com borda suave."""
    m = np.zeros((alt, larg), dtype=np.uint8)
    cv2.ellipse(m, (larg // 2, alt // 2), (larg // 2 - feather, alt // 2 - feather),
                0, 0, 360, 255, -1)
    m = cv2.GaussianBlur(m, (feather * 2 + 1, feather * 2 + 1), 0)
    return (m.astype(np.float32) / 255.0)[:, :, None]


def caixa_do_rosto(landmarks, w, h, aspecto):
    """Caixa de recorte em volta do rosto, ja com folga e no formato do buraco."""
    xs = [p.x for p in landmarks]
    ys = [p.y for p in landmarks]
    x0, x1 = min(xs) * w, max(xs) * w
    y0, y1 = min(ys) * h, max(ys) * h
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 - (y1 - y0) * FOLGA_TESTA / 2
    rw, rh = (x1 - x0) * FOLGA_ROSTO, (y1 - y0) * (FOLGA_ROSTO + FOLGA_TESTA)
    # ajusta a caixa pro mesmo formato (largura/altura) do buraco
    if rw / rh > aspecto:
        rh = rw / aspecto
    else:
        rw = rh * aspecto
    return cx, cy, rw, rh


def main():
    if PRIORIDADE_BAIXA and baixar_prioridade():
        print("Prioridade baixa ativada: seu jogo vem primeiro.")

    cena_base, (bx, by, bw, bh) = montar_cena(escolher_moldura(), LARGURA, ALTURA)
    print(f"Buraco da moldura: centro=({bx:.0f},{by:.0f}) tamanho={bw:.0f}x{bh:.0f}")

    # regiao (patch) do video onde o rosto vai ser colado
    px = int(bx - bw / 2) - 4
    py = int(by - bh / 2) - 4
    pw, ph = int(bw) + 8, int(bh) + 8
    mascara = mascara_oval(pw, ph)
    fundo_patch = cena_base[py:py + ph, px:px + pw].astype(np.float32) * (1 - mascara)

    landmarker = FaceLandmarker.create_from_options(FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=achar_modelo()),
        running_mode=RunningMode.VIDEO,
        num_faces=1,
    ))

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    ok, frame = cap.read() if cap.isOpened() else (False, None)
    if not ok:
        print("ERRO: nao consegui abrir a webcam.")
        print("Feche outros programas que estejam usando a camera e tente de novo.")
        sys.exit(1)

    try:
        cam_virtual = pyvirtualcam.Camera(width=LARGURA, height=ALTURA, fps=FPS,
                                          fmt=pyvirtualcam.PixelFormat.BGR)
    except Exception as e:
        print("ERRO: nao consegui criar a camera virtual.")
        print("Confira se o OBS esta instalado e se nada mais esta usando a camera virtual.")
        print(f"Detalhe tecnico: {e}")
        sys.exit(1)

    print(f"\nMolduraCam rodando! ({LARGURA}x{ALTURA} @ {FPS}fps)")
    print(f"Camera virtual: {cam_virtual.device}")
    print("No Discord, selecione essa camera em Voz e Video. Ctrl+C para sair.")

    caixa = None  # (cx, cy, w, h) suavizada
    inicio = time.time()

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            if ESPELHAR:
                frame = cv2.flip(frame, 1)
            fh, fw = frame.shape[:2]

            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB,
                              data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            ts_ms = int((time.time() - inicio) * 1000)
            resultado = landmarker.detect_for_video(mp_img, ts_ms)

            if resultado.face_landmarks:
                nova = caixa_do_rosto(resultado.face_landmarks[0], fw, fh, pw / ph)
                if caixa is None:
                    caixa = nova
                else:  # suaviza pro rosto nao ficar tremendo na moldura
                    a = SUAVIZACAO
                    caixa = tuple(a * n + (1 - a) * v for n, v in zip(nova, caixa))

            saida = cena_base.copy()
            if caixa is not None:
                cx, cy, rw, rh = caixa
                x0 = int(max(0, min(cx - rw / 2, fw - rw)))
                y0 = int(max(0, min(cy - rh / 2, fh - rh)))
                x1, y1 = int(min(x0 + rw, fw)), int(min(y0 + rh, fh))
                rosto = frame[y0:y1, x0:x1]
                if rosto.size:
                    rosto = cv2.resize(rosto, (pw, ph), interpolation=cv2.INTER_LINEAR)
                    patch = rosto.astype(np.float32) * mascara + fundo_patch
                    saida[py:py + ph, px:px + pw] = patch.astype(np.uint8)

            cam_virtual.send(saida)
            cam_virtual.sleep_until_next_frame()
    except KeyboardInterrupt:
        print("\nEncerrando. Ate a proxima!")
    finally:
        cap.release()
        cam_virtual.close()
        landmarker.close()


if __name__ == "__main__":
    main()
