# Reprocessamento da reunião 5 — 24/09/2026

## Medição local

O mesmo áudio de 5.122,485 segundos (85 min 22 s) foi transcrito duas vezes pelo Faster Whisper `small`, em português, com `beam_size=5`, VAD e timestamps de palavras.

| Execução | Configuração | Tempo total do job | Fator de tempo real | Segmentos |
| --- | --- | ---: | ---: | ---: |
| Original | CPU, `int8` | 58 min 0 s | 0,679 | 2.423 |
| Reprocessamento | RTX 3050 4 GB, `int8_float16` | 7 min 2 s | 0,082 | 2.491 |

O reprocessamento foi **8,2 vezes mais rápido**. Ele criou uma nova transcrição; a primeira permaneceu no banco. A versão na GPU foi ativada pelo fluxo existente do aplicativo. Não foi executada identificação de falantes nem resumo nessa rodada. O áudio WAV normalizado já existia e foi reutilizado.

Durante 106 amostras com intervalo de aproximadamente 3 segundos, iniciadas cerca de 70 segundos depois do começo do job, foram observados: máximo de 2.366 MB de memória privada do processo; máximo de 591 MB de conjunto de trabalho físico do processo; mínimo de 1.146 MB de RAM disponível no sistema; média de 11,5% da CPU total (16 processadores lógicos); média de 55,4% e pico de 89% de uso da GPU; pico de 1.128 MB de VRAM ocupada no dispositivo. A VRAM inclui outros usos do sistema e a amostragem não captou o primeiro minuto, portanto os máximos não são picos garantidos da execução inteira. O CSV da medição permanece fora do repositório.

As duas transcrições têm 91,5% de concordância média de tokens em janelas de um minuto, calculada sem publicar o conteúdo. Isso **não** mede precisão: para comparar qualidade, é necessário um trecho revisado por uma pessoa como referência.

## Teste curto de modelo

Trecho de 120 segundos a partir do minuto 30, na mesma GPU e com `int8_float16`, `beam_size=5` e timestamps de palavras:

| Modelo | Inferência depois da carga | VRAM total máxima observada | Acordo com transcrição original |
| --- | ---: | ---: | ---: |
| `small` | 7,95 s | 967 MB | 91,8% |
| `turbo` | 8,28 s | 1.671 MB | 89,4% |

O acordo com a transcrição original também não é uma medida de precisão. O Turbo coube na GPU, mas não demonstrou vantagem de velocidade nesse trecho. A carga dele, já baixado, levou cerca de 7 s, contra 2,4 s do `small`. Manter `small` como padrão até haver uma referência humana de qualidade e mais amostras.

## Próximos ganhos

1. Reduzir buscas e reconstruções completas da transcrição na interface. O polling de captura foi tornado adaptativo e o progresso em segundo plano não recarrega mais a transcrição inteira. Uma API paginada para transcrições ainda em andamento é o próximo passo se o DOM continuar pesado.
2. Exibir CPU, GPU, VRAM e RAM com amostragem assíncrona e cache, sem executar `nvidia-smi` em cada requisição da interface.
3. Medir o tempo de cada fase (normalização, carga, inferência e finalização) em jobs futuros. Não há evidência de que reconverter o WAV melhore a inferência; o pipeline já reutiliza PCM mono de 16 kHz.
4. Considerar isolar a inferência em um subprocesso se a memória privada retida após o job continuar causando pressão. O modelo foi descarregado, mas o processo ainda reservava cerca de 1,47 GB; o conjunto de trabalho físico já havia caído para cerca de 81 MB. Isso exige mudança de arquitetura e teste de recuperação de falhas.

O [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) documenta ganhos de quantização e ressalta que seus benchmarks usam hardware diferente. O [cartão dos modelos Whisper](https://github.com/openai/whisper/blob/main/model-card.md) descreve o Turbo como multilíngue e otimizado para velocidade; isso não substitui a medição nesta RTX 3050. A [documentação do CTranslate2](https://opennmt.net/CTranslate2/quantization.html) descreve `int8_float16` e suas condições de suporte.
