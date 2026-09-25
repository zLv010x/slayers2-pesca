# Slayers 2 • Pesca

Macro de pesca automática para o Slayers 2 (Roblox), com aviso no Discord de cada item pego.

## Instalar (uma vez)

1. Instale o Python 3.12 ou mais novo em https://www.python.org/downloads/ e marque **"Add python.exe to PATH"**.
2. Dê dois cliques em `Instalar.bat`.

## Usar

1. No Roblox: desligue **Screen Shake** e **Shift Lock**, equipe a vara e posicione a câmera como quer pescar.
2. Abra o **Iniciar** (o atalho com a logo do peixe, criado pelo `Instalar.bat`). Se ele não aparecer, use o `Iniciar.bat`.
3. Aba **Configurar**:
   - **Marcar ponto**: clique na água onde a vara deve lançar. A câmera (bússola) fica gravada junto.
   - **Tecla da vara**: o número do slot da vara na hotbar.
   - **Ajustar área**: só se a barra do minigame não for detectada.
4. Aba **Relog** (opcional, precisa do gamepass **Set Spawn**):
   - ligue **Reconectar sozinho se o jogo cair**;
   - marque **Tenho o gamepass Set Spawn** e, se já setou, **Já setei o spawn no ponto de pesca**
     (se não setou, a macro seta sozinha depois do 1º peixe, ou use **Setar spawn agora**);
   - escolha **Tenho VIP** (volta para o seu servidor privado) ou **Não tenho VIP** e digite o
     **nick exato** do dono do servidor. A linha colorida no alto da aba diz o que ainda falta.
5. Aba **Discord** (opcional): cole o link do webhook e o seu ID para ser marcado nos itens raros.
6. Aperte **F1** (ou o atalho que você escolher) para começar e parar.

## O que a macro faz sozinha

- Confere se a vara está na mão antes de lançar e só aperta a tecla da vara quando precisa.
- Pausa se o Roblox sair da frente, e volta quando estiver tudo certo.
- Se a câmera girar, tenta girar de volta sozinha (arrastando com o botão direito); só pausa
  esperando você se não conseguir. Numa pausa longa mexe o mouse 1 px a cada 4 min, para o
  Roblox não desconectar por inatividade.
- Se algo der errado (vara não equipa, vários lançamentos sem peixe, erro inesperado), avisa no
  Discord, espera e tenta de novo. Se desistir depois de várias falhas seguidas, **reinicia sozinha**
  depois de 5 min (até 3 vezes por hora; muda em **Avançado**).
- Se você mexer no mouse bem na hora do lançamento, ela espera o mouse ficar livre e lança de novo.
- Se o jogo cair (**menu principal** ou **Disconnected**): com o auto relog ligado (aba **Relog**),
  reconecta, entra no servidor privado, nasce no spawn setado e volta a pescar. Desligado, ela para
  e avisa no Discord: entre de novo, volte ao ponto de pesca e aperte F1. Se a conta entrou em
  outro PC (erro 264), nunca reconecta.
- **Overlay** por cima do jogo com o tempo de macro, o total de cada peixe e item e as iscas gastas.
  Fica em cima da party; com a pesca parada dá para arrastar. Liga/desliga e "Voltar para a party"
  em **Configurar → Janela**. Ele não aparece nos prints da macro e, pescando, o clique passa através dele.
- **Parsec / OBS**: normalmente a janela da macro e o overlay somem de qualquer captura enquanto
  pesca (pelo Parsec parece que minimizou). Ligue **Configurar → Janela → Aparecer no Parsec / OBS**
  para vê-los; a macro se apaga dos próprios prints, então deixe a janela no canto esquerdo (ela avisa
  se estiver cobrindo os avisos dos itens, a barra, a hotbar ou a bússola).
- **Histórico** (aba Sessão): cada etiqueta de raridade liga/desliga aquela raridade na lista. Desligar
  só esconde: os drops continuam guardados e voltam quando você liga de novo.
- **A sessão fica guardada** (histórico, contagens, tempo e iscas gastas), mesmo fechando a macro, até
  você clicar em **Resetar** na aba Sessão. O CSV de cada sessão continua em `logs/`.
- **Item acompanhado** (aba Discord, padrão "Ore"): total só desse item na sessão (o Ore mythic;
  Refinement Ore é outro item), mostrado na janela e em todo aviso do Discord.
- Registra o principal em `logs/macro.log`. Para investigar um problema, ligue **Avançado → Modo diagnóstico**:
  log detalhado e um print em `logs/evidencias/` a cada problema (deixa a macro mais pesada, então só quando precisar).
- **Cão de guarda**: se a macro travar pescando (ficar 5 min sem sinal de vida), ele fecha e abre a macro
  de novo sozinho, volta a pescar e avisa no Discord (no máximo 3 vezes por hora). Onde ela estava parada
  fica em `logs/travamento.txt`; o que o cão de guarda fez, em `logs/cao-de-guarda.log`.
- Não deixa o PC dormir nem a tela apagar enquanto está pescando.
- Guarda tudo o que pegou em `logs/sessao-*.csv`.
- Usa um **catálogo de itens** para saber se um item já é conhecido, corrigir erros de leitura
  do nome e confirmar a raridade:
  - `catalogo/` é o catálogo **compartilhado**, que vem junto com a macro. Ela só lê essa pasta.
  - `catalogo_local/` é o **seu**: itens que ainda não estão no compartilhado entram aqui
    (uma imagem por item, sem repetir), junto com as suas contagens.
  - Item que não está em nenhum dos dois aparece no Discord como "Primeira vez no catálogo".
  - Nome lido torto pelo OCR ("Clov.tn Fish", "Jzebra Fish", "Golden FEh") vira o item certo. Ao abrir,
    a macro arruma o catálogo local: leituras erradas antigas entram no item certo e lixo sai.
  - Para mandar os itens novos para o compartilhado: `python src/catalog.py publicar`.
  - Cada item do `catalogo/itens.json` é uma **ficha**: `"name"` (nome certo), `"image"` (imagem em
    `catalogo/imagens/`) e `"rarity"` (common, rare, epic, legendary ou mythic). O aviso no Discord e na
    janela usa a ficha: nome, imagem e raridade vêm dela, não da cor lida na tela. A cor só vale para item
    que ainda não tem ficha.
  - Para corrigir um item, edite a ficha: troque o `"rarity"`, troque a imagem ou ponha a leitura errada
    em `"aliases"`. O `publicar` não mexe na raridade que já está na ficha.

## Atalhos

Todos podem ser trocados em **Configurar → Atalhos**. Os padrões são: F1 (iniciar e parar), F2 (marcar o ponto) e F3 (fechar).

## Privacidade

O `config.json` guarda o link do webhook, que funciona como uma senha. Não mande esse arquivo para ninguém. Se for passar a macro para alguém, passe a pasta sem o `config.json`.

---
A detecção da barra do minigame foi portada da macro original do 1vtt (youtube.com/@1-vtt).
