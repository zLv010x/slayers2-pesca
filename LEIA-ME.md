# Slayers 2 • Pesca

Macro de pesca automática para o Slayers 2 (Roblox), com aviso no Discord de cada item pego.

## Instalar (uma vez)

1. Instale o Python 3.12 ou mais novo em https://www.python.org/downloads/ e marque **"Add python.exe to PATH"**.
2. Dê dois cliques em `Instalar.bat`.

## Usar

1. No Roblox: desligue **Screen Shake** e **Shift Lock**, equipe a vara e posicione a câmera como quer pescar.
2. Abra `Iniciar.bat`.
3. Aba **Configurar**:
   - **Marcar ponto**: clique na água onde a vara deve lançar. A câmera (bússola) fica gravada junto.
   - **Tecla da vara**: o número do slot da vara na hotbar.
   - **Ajustar área**: só se a barra do minigame não for detectada.
4. Aba **Discord** (opcional): cole o link do webhook e o seu ID para ser marcado nos itens raros.
5. Aperte **F1** (ou o atalho que você escolher) para começar e parar.

## O que a macro faz sozinha

- Confere se a vara está na mão antes de lançar e só aperta a tecla da vara quando precisa.
- Pausa se o Roblox sair da frente ou se a câmera girar, e volta quando estiver tudo certo.
- Para e avisa no Discord se não conseguir equipar a vara ou se vários lançamentos seguidos falharem.
- Guarda tudo o que pegou em `logs/sessao-*.csv`.

## Atalhos

Todos podem ser trocados em **Configurar → Atalhos**. Os padrões são: F1 (iniciar e parar), F2 (marcar o ponto) e F3 (fechar).

## Privacidade

O `config.json` guarda o link do webhook, que funciona como uma senha. Não mande esse arquivo para ninguém. Se for passar a macro para alguém, passe a pasta sem o `config.json`.

---
A detecção da barra do minigame foi portada da macro original do 1vtt (youtube.com/@1-vtt).
