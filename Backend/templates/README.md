# Backend/templates

Catálogo de templates regulatórios usados pelo Regulatory Documentation Copilot do BridgeMedAI.

## Estrutura

Os templates estão organizados por **categoria regulatória** (uma subpasta por categoria):

- `Change Management/` — gestão de alterações
- `Clinical Evaluation/` — CER, CEP, PMCF, literature search
- `Complaint and Feedback Management/` — feedback e reclamações
- `Corrective and Preventive Actions/` — CAPA
- `Cybersecurity/` — IEC 81001-5-1, MDCG 2019-16
- `Design and Development/` — SRS, software architecture, GSPR, etc.
- `Risk Management/` — ISO 14971 plan/file/report
- `Usability/` — IEC 62366 UE plan/file/test
- `Vigilance/` — incidentes, FSN, FSCA

Templates pre-existentes do BridgeMedAI (ex: `pmcf_template.docx`) ficam na raiz desta pasta com `metadata_status: "legacy"` no registry.

## Convenção de nomes

Cada template segue o padrão `{TYPE}-{AREA}-{NN}_{descriptive_name}.{ext}`:

| Prefixo | Significado                                              |
|---------|----------------------------------------------------------|
| `TMP-`  | Template — documento de conteúdo para ser autorado       |
| `FRM-`  | Form / checklist                                         |
| `SOP-`  | Standard Operating Procedure                             |
| `LST-`  | List / tracking spreadsheet                              |

Áreas: `CE` (Clinical Evaluation), `RM` (Risk Management), `SW` (Software), `HF` (Human Factors / Usability), `CC` (Change Control), `CP` (CAPA), `CM` (Complaints), `VI` (Vigilance), `IU` (Intended Use), `TD` (Technical Documentation).

## registry.json

Metadata canónica de todos os templates. Consumido pelo Template Registry, Document Orchestrator e Auto-fill Engine.

Cada entrada tem: `id`, `name`, `file`, `category`, `doc_type`, `description`, `keywords`, `regulations`, `themes`, `mandatory_sections`, `optional_sections`, `auto_fillable_fields`, `human_required_fields`, `dependencies` (docs que devem existir antes), `feeds_into` (docs que consomem este), `workflow_priority`, `metadata_status`.

**Importante:** todas as entradas têm `metadata_status: "seed"` — foram geradas por LLM com conhecimento regulatório base e precisam de **revisão por especialista** antes de uso em produção. Marcar `metadata_status: "reviewed"` após validação.

### Campos partilhados (field dictionary)

Os IDs em `auto_fillable_fields` e `human_required_fields` são chaves canónicas reutilizadas entre templates. Exemplo: `intended_purpose` é o mesmo campo em `TMP-CE-01`, `TMP-CE-02`, `TMP-SW-04`, `TMP-RM-02`, etc. Quando o utilizador define `intended_purpose` na conversa, o Auto-fill Engine pré-preenche-o em todos os templates que o declaram.

## Grafo de dependências

Cada template declara `dependencies` (o que precisa antes) e `feeds_into` (o que alimenta depois). Usado pelo Document Orchestrator para sequenciar workflows multi-documento.

Exemplo: `TMP-CE-05` (PMCF Plan) depende de `TMP-CE-01` (CER) e `TMP-RM-03` (Risk Management Report), e alimenta `TMP-CE-06` (PMCF Report).
