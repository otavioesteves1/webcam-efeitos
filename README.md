# 🎥 Webcam Efeitos

Efeitos divertidos pra sua webcam no Discord (ou em qualquer app de vídeo), feitos em Python.
O truque: os programas leem sua webcam real, desenham coisas por cima e mandam o resultado
pra uma **câmera virtual** — aí é só escolher a "OBS Virtual Camera" no Discord.

> *Fun virtual-camera effects in Python: blink detection with sound + Pokémon walking across your webcam feed (vscode-pokemon style). README in Brazilian Portuguese.*

Tem dois programas aqui dentro:

| Projeto | O que faz |
|---|---|
| **[01_PIS-CAM](01_PIS-CAM/)** | Detecta quando você **pisca**: toca um bip no seu PC e mostra um "PISCOU!" no vídeo que seus amigos veem |
| **[02_GIF-WEBCAM](02_GIF-WEBCAM/)** | **Pokémons** em pixel-art passeiam na parte de baixo do seu vídeo, no estilo do plugin [vscode-pokemon](https://github.com/jakobhoeg/vscode-pokemon) |
| **[03_MOLDURA-CAM](03_MOLDURA-CAM/)** | Seu **rosto dentro de uma moldura** (tipo "cara no buraco" de parque de diversão): a câmera acha seu rosto e encaixa ele no buraco da imagem — o resto some |

## O que você precisa

- **Windows** com uma webcam
- **Python 3.12+** — [python.org](https://www.python.org/downloads/)
- **OBS Studio** instalado — [obsproject.com](https://obsproject.com/) (não precisa abrir ele, só instalar: o driver de câmera virtual vem junto)

Instale as bibliotecas:

```
pip install opencv-python mediapipe pyvirtualcam pillow
```

## Como usar (os dois funcionam igual)

1. Dê dois cliques no `.bat` do projeto (`PiscaCam.bat` ou `GifCam.bat`) — uma janela de terminal abre e fica rodando
2. No Discord: **Configurações → Voz e vídeo → Câmera → "OBS Virtual Camera"**
3. Pra encerrar, feche a janela do terminal (ou Ctrl+C)

⚠️ Só um por vez! Os dois usam a mesma webcam e a mesma câmera virtual, então rodar os dois juntos não rola.

## 👁️ 01_PIS-CAM

Detecta piscadas usando o FaceLandmarker do MediaPipe (o modelo `face_landmarker.task`
já está na pasta). Quando você pisca:

- toca um bip no **seu** PC (o áudio não vai pro Discord, é só pra você)
- aparece um **"PISCOU!"** com borda amarela no vídeo — isso sim seus amigos veem
- um contador de piscadas fica no canto

Ajustes no topo do [`pisca_cam.py`](01_PIS-CAM/pisca_cam.py): sensibilidade da piscada
(`LIMIAR_FECHADO`), duração do efeito, frequência do bip, espelhar o vídeo, esconder o contador.

## 🐛 02_GIF-WEBCAM

Pokémons de pixel-art andando na parte de baixo do seu vídeo. Eles caminham, param um
pouquinho, viram e continuam — cada um com velocidade própria.

**Escolha seu time no [`pokemons.txt`](02_GIF-WEBCAM/pokemons.txt)**, um por linha:

```
pikachu              ← tamanho padrão
pikachu 30           ← número de 1 a 100 = tamanho (% da altura da tela)
charizard 50 shiny   ← dá pra combinar tamanho + shiny
metapod
metapod              ← repetir = vários iguais na tela
```

Nomes em inglês, minúsculos (gen1 até gen4, ~500 pokémons). Na primeira vez que usar um
pokémon novo, o gif do bichinho é baixado sozinho do repositório do
[vscode-pokemon](https://github.com/jakobhoeg/vscode-pokemon) e guardado na pasta `sprites/`
— depois disso funciona offline.

**Extras:**

- `python baixar_gen1.py` — baixa os 151 da gen1 de uma vez
- [`catalogo.html`](02_GIF-WEBCAM/catalogo.html) — abra no navegador depois de baixar a gen1:
  uma Pokédex com os sprites animados, busca por nome e clique-pra-copiar

**Feito pra rodar junto com jogos** sem atrapalhar o FPS:

- roda em **prioridade baixa** — o Windows sempre dá CPU pro jogo primeiro
- a transparência dos sprites é pré-calculada (nada de conta pesada por frame)
- 20 fps por padrão (suave no Discord e leve; mude `FPS` no topo do `gif_cam.py` se quiser)
- consumo medido: ~20% de um núcleo de CPU, mesmo com pokémon gigante na tela

## 🪳 03_MOLDURA-CAM

O clássico "cara no buraco": o programa detecta seu rosto na webcam, recorta só ele
e encaixa no buraco branco da `moldura.png`. Seu corpo e o fundo desaparecem — o que
vai pro Discord é a moldura com a sua cara.

- **Troque a moldura à vontade:** substitua o `moldura.png` por qualquer imagem que
  tenha um buraco **branco puro** oval ou redondo (que não encoste nas bordas) — o
  programa encontra o buraco sozinho
- O rosto acompanha você com suavização (sem tremedeira), e o vídeo é espelhado por
  padrão pra você se reconhecer melhor (`ESPELHAR` no topo do `moldura_cam.py`)
- Ajustes no topo do [`moldura_cam.py`](03_MOLDURA-CAM/moldura_cam.py): folga do recorte
  do rosto, suavização do movimento, fps

## Créditos

- Sprites de pokémon do projeto [vscode-pokemon](https://github.com/jakobhoeg/vscode-pokemon)
  (MIT) de [@jakobhoeg](https://github.com/jakobhoeg). Pokémon © Nintendo / Game Freak —
  este é um projeto de diversão pessoal, sem fins comerciais.
- Detecção de rosto: [MediaPipe](https://developers.google.com/mediapipe) (Google, Apache 2.0)
- Câmera virtual: [pyvirtualcam](https://github.com/letmaik/pyvirtualcam) + driver do
  [OBS Studio](https://obsproject.com/)

---

Feito com [Claude Code](https://claude.com/claude-code) 🤖
