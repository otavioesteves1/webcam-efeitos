# -*- coding: utf-8 -*-
"""
PiscaCam — camera virtual com detector de piscada
Le a webcam real (C920), detecta quando voce pisca e:
  - toca um bip no seu PC
  - mostra "PISCOU!" no video que vai pro Discord

No Discord: Configuracoes > Voz e video > Camera > "OBS Virtual Camera"

Pra rodar:    python pisca_cam.py
Pra encerrar: Ctrl+C no terminal.
"""

import os
import sys
import time
import threading

os.environ["GLOG_minloglevel"] = "2"  # silencia avisos internos do MediaPipe

import cv2
import winsound
import pyvirtualcam
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker, FaceLandmarkerOptions, RunningMode,
)

# ---------- Ajustes (mexa a vontade) ----------
LARGURA, ALTURA, FPS = 1280, 720, 30

# O modelo devolve 0.0 (olho aberto) ate 1.0 (olho fechado).
# Acima de LIMIAR_FECHADO conta como piscada.
# Detectando demais? Aumente (ex: 0.6). Nao detecta? Diminua (ex: 0.4).
LIMIAR_FECHADO = 0.5

DURACAO_EFEITO = 0.7          # segundos que o "PISCOU!" fica na tela
BIP_FREQ, BIP_MS = 900, 120   # frequencia (Hz) e duracao (ms) do bip
MOSTRAR_CONTADOR = True       # contador de piscadas no canto do video
ESPELHAR = False              # True = video espelhado (como um espelho)
# ----------------------------------------------

MODELO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "face_landmarker.task")


def bip():
    threading.Thread(target=winsound.Beep, args=(BIP_FREQ, BIP_MS), daemon=True).start()


def desenha_efeito(frame):
    """Texto 'PISCOU!' + borda colorida enquanto o efeito estiver ativo."""
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 220, 255), 18)
    texto = "PISCOU!"
    fonte = cv2.FONT_HERSHEY_TRIPLEX
    escala = 3.0
    (tw, th), _ = cv2.getTextSize(texto, fonte, escala, 6)
    x, y = (w - tw) // 2, (h + th) // 2
    cv2.putText(frame, texto, (x, y), fonte, escala, (0, 0, 0), 14, cv2.LINE_AA)
    cv2.putText(frame, texto, (x, y), fonte, escala, (0, 220, 255), 6, cv2.LINE_AA)


def desenha_contador(frame, n):
    cv2.putText(frame, f"piscadas: {n}", (20, 45),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.putText(frame, f"piscadas: {n}", (20, 45),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)


def nivel_piscada(resultado):
    """Retorna 0..1: quao fechados os olhos estao (media dos dois)."""
    if not resultado.face_blendshapes:
        return None
    valores = {b.category_name: b.score for b in resultado.face_blendshapes[0]}
    return (valores.get("eyeBlinkLeft", 0) + valores.get("eyeBlinkRight", 0)) / 2.0


def main():
    if not os.path.exists(MODELO):
        print("ERRO: arquivo face_landmarker.task nao encontrado na pasta do script.")
        sys.exit(1)

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    ok, frame = cap.read() if cap.isOpened() else (False, None)
    if not ok:
        print("ERRO: nao consegui abrir a webcam.")
        print("Feche outros programas que estejam usando a camera (Discord, OBS, navegador) e tente de novo.")
        sys.exit(1)
    h, w = frame.shape[:2]

    landmarker = FaceLandmarker.create_from_options(FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODELO),
        running_mode=RunningMode.VIDEO,
        num_faces=1,
        output_face_blendshapes=True,
    ))

    try:
        cam_virtual = pyvirtualcam.Camera(width=w, height=h, fps=FPS,
                                          fmt=pyvirtualcam.PixelFormat.BGR)
    except Exception as e:
        print("ERRO: nao consegui criar a camera virtual.")
        print("Confira se o OBS Studio esta instalado (o driver vem com ele) e")
        print("se o OBS NAO esta com a 'Camera Virtual' dele ligada ao mesmo tempo.")
        print(f"Detalhe tecnico: {e}")
        sys.exit(1)

    print(f"PiscaCam rodando! ({w}x{h} @ {FPS}fps)")
    print(f"Camera virtual: {cam_virtual.device}")
    print("No Discord, selecione essa camera em Voz e Video. Ctrl+C para sair.")

    olho_fechado = False
    piscadas = 0
    efeito_ate = 0.0
    inicio = time.time()

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            if ESPELHAR:
                frame = cv2.flip(frame, 1)

            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB,
                              data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            ts_ms = int((time.time() - inicio) * 1000)
            nivel = nivel_piscada(landmarker.detect_for_video(mp_img, ts_ms))

            if nivel is not None:
                if nivel > LIMIAR_FECHADO and not olho_fechado:
                    olho_fechado = True
                elif nivel <= LIMIAR_FECHADO and olho_fechado:
                    olho_fechado = False
                    piscadas += 1
                    efeito_ate = time.time() + DURACAO_EFEITO
                    bip()
                    print(f"Piscada #{piscadas}")

            if time.time() < efeito_ate:
                desenha_efeito(frame)
            if MOSTRAR_CONTADOR:
                desenha_contador(frame, piscadas)

            cam_virtual.send(frame)
            cam_virtual.sleep_until_next_frame()
    except KeyboardInterrupt:
        print(f"\nEncerrando. Total de piscadas: {piscadas}")
    finally:
        cap.release()
        cam_virtual.close()
        landmarker.close()


if __name__ == "__main__":
    main()
