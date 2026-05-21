# Testes de Dispositivos — BridgeMedAI

Como correr os testes locais (Backend):

1. Ativa o virtualenv na pasta `Backend/Python` (se ainda não estiver activo):

```powershell
cd "c:\Users\joaof\OneDrive\Ambiente de Trabalho\PECI\BridgeMedAI\Backend\Python"
.\.venv\Scripts\Activate.ps1
```

2. Instala as dependências (se ainda não as instalaste):

```powershell
python -m pip install --upgrade pip
pip install -r ..\requirements.txt
```

3. Executa os testes com `pytest` a partir da pasta `Backend`:

```powershell
cd ..\
pytest Backend/tests -q
```

O ficheiro `TEST_MATRIX.md` contém a matriz de correspondência entre testes e dispositivos.

Se quiseres, posso:
- adicionar testes adicionais (calibração, tolerâncias, histórico de medições),
- gerar mocks de hardware para testes de integração,
- ou integrar estes testes num pipeline CI (GitHub Actions).
