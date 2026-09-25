# Instalação no Windows

Este guia complementa a seção de instalação do [README](../README.md) e cobre a configuração opcional de resumos locais.

## Instalação base

No diretório do repositório, execute `install.ps1 -Mvp` para preparar a captura local, o Faster Whisper, o modelo ASR `small` e as ferramentas de mídia. Consulte o README para pré-requisitos, início do aplicativo, áudio e verificações da instalação.

## Habilitar resumos locais

O perfil MVP mantém o resumo local opcional. Para instalar o runtime e baixar o modelo **LFM2.5 1.2B Q4** (aproximadamente **731 MB**), execute na raiz do repositório:

```powershell
.\install.ps1 -Mvp -InstallSummaries
```

Se **Configurações → Geral → Modelos de IA** já aponta para um diretório personalizado, informe o mesmo caminho ao instalador. Isso evita baixar os pesos em uma pasta diferente da ativa no aplicativo:

```powershell
.\install.ps1 -Mvp -InstallSummaries -ModelsDirectory "D:\Meeting\Models"
```

Substitua o exemplo pelo valor real configurado em **Modelos de IA**. O parâmetro `-ModelsDirectory` também deve apontar para o mesmo diretório usado nas verificações e no início do aplicativo.

Quando a instalação terminar, feche e reinicie o Meeting by Solvit para que o processo Python carregue o runtime recém-instalado. Em **Configurações → AI engine**, selecione **LFM2.5 1.2B Q4** se ainda não estiver ativo e use **Carregar**. O catálogo permite instalar ou selecionar outro perfil; a ação direta da checklist inicial também leva à configuração correspondente.

Confirme os estados antes de gerar notas: a checklist deve indicar que o modelo está instalado e pronto para carregar; depois da ação **Carregar**, o motor deve aparecer pronto/na memória. Se o resumo continuar indisponível, confira o runtime, o perfil selecionado e o caminho de modelos em **AI engine**.

## CPU do resumo e CUDA do ASR

No Windows com **Python 3.13**, o instalador configura `llama-cpp-python` para CPU porque a wheel CUDA de resumo disponível para este instalador não cobre essa versão. Isso é independente do backend PyTorch usado pelo Faster Whisper: o ASR pode permanecer em CUDA, enquanto a geração do resumo usa CPU. O resumo pode levar mais tempo em reuniões longas e usar capacidade de CPU durante a geração.
