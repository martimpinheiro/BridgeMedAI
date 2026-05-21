# Matriz de Testes — Conformidade Regulatória

Esta matriz mapeia os testes de conformidade MDR e normas ISO/IEC definidos em `test_devices.py` para cada dispositivo.

| Teste                                     | Termómetro | Medidor Tensão | Glicosímetro | Oxímetro |
|-------------------------------------------|:---------:|:---------------:|:----------:|:-------:|
| **Classificação MDR Válida**              |    ✅     |       ✅        |     ✅     |   ✅    |
| Classe: IIa                               |    ✅     |       ❌ IIb    |     ✅     |   ✅    |
| **Regra MDR Atribuída**                   |    ✅     |       ✅        |     ✅     |   ✅    |
| Rule 1 (Non-invasive monitoring)          |    ✅     |       ❌        |     ❌     |   ❌    |
| **Nível de Risco Definido**               |    ✅     |       ✅        |     ✅     |   ✅    |
| Risk: low                                 |    ✅     |       ❌ medium |     ✅     |   ✅    |
| **Normas ISO/IEC Aplicáveis**             |    ✅     |       ✅        |     ✅     |   ✅    |
| ISO 80601-2-56 (Thermometers)             |    ✅     |       ❌        |     ❌     |   ❌    |
| ISO 80601-2-30 (BP measurement)           |    ❌     |       ✅        |     ❌     |   ❌    |
| ISO 15197 (Glucose measurement)           |    ❌     |       ❌        |     ✅     |   ❌    |
| ISO 80601-2-61 (Pulse oximeters)          |    ❌     |       ❌        |     ❌     |   ✅    |
| ISO 13485:2016 (QMS — Obrigatória)        |    ✅     |       ✅        |     ✅     |   ✅    |
| ISO 14971:2019 (Risk Management)          |    ✅     |       ✅        |     ✅     |   ✅    |
| **Documentação Regulatória Requerida**    |    ✅     |       ✅        |     ✅     |   ✅    |
| Technical File                            |    ✅     |       ✅        |     ✅     |   ✅    |
| Risk Management Report                    |    ✅     |       ✅        |     ✅     |   ✅    |
| Quality Management System                 |    ✅     |       ✅        |     ✅     |   ✅    |
| Clinical Evaluation Report                |    ❌     |       ✅        |     ❌     |   ❌    |
| Post-market Surveillance Plan             |    ❌     |       ❌        |     ✅     |   ❌    |

## Referências Regulatórias

- **MDR**: Medical Device Regulation (EU) 2017/745
- **ISO 13485:2016**: Quality Management Systems for medical devices
- **ISO 14971:2019**: Risk Management for medical devices
- **ISO 80601-2-****: Specific standards for each device type
- **IEC 60601-1:2005**: Electrical safety requirements for medical equipment

Notas:
- Estes testes focam em **conformidade regulatória** e **identificação de normas aplicáveis**.
- Não testam funcionalidade operacional (bateria, conectividade, medições).
- Objetivo: garantir que cada dispositivo é corretamente **classificado**, tem **riscos avaliados** e **documentação identificada** antes do envio para conformidade.
