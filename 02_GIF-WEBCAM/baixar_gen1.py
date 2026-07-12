# -*- coding: utf-8 -*-
"""
Baixa de uma vez os sprites (andar + parado) dos 151 pokemons da gen1
pra pasta sprites/. Opcional: o gif_cam.py ja baixa sob demanda o que
estiver no pokemons.txt — isso aqui e util pro catalogo.html mostrar
todo mundo e pra usar offline.

Uso: python baixar_gen1.py
"""

import os
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PASTA_SPRITES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprites")
URL_BASE = "https://raw.githubusercontent.com/jakobhoeg/vscode-pokemon/main/media/gen1"
API = "https://api.github.com/repos/jakobhoeg/vscode-pokemon/contents/media/gen1"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def baixa_um(nome):
    try:
        for anim in ("walk", "idle"):
            destino = os.path.join(PASTA_SPRITES, f"{nome}_default_{anim}.gif")
            if not os.path.exists(destino):
                dados = get(f"{URL_BASE}/{nome}/default_{anim}_8fps.gif")
                with open(destino, "wb") as f:
                    f.write(dados)
        return nome, "ok"
    except Exception as e:
        return nome, f"FALHOU: {e}"


def main():
    nomes = sorted(x["name"] for x in json.loads(get(API)) if x["type"] == "dir")
    print(f"{len(nomes)} pokemons na gen1, baixando o que faltar...")
    os.makedirs(PASTA_SPRITES, exist_ok=True)
    with ThreadPoolExecutor(max_workers=12) as ex:
        resultados = list(ex.map(baixa_um, nomes))
    falhas = [(n, r) for n, r in resultados if r != "ok"]
    print(f"prontos: {len(resultados) - len(falhas)}, falhas: {len(falhas)}")
    for n, r in falhas:
        print(" ", n, r)


if __name__ == "__main__":
    main()
