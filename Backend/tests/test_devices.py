import pytest

# Definição de 4 dispositivos com classificação MDR e normas de conformidade
@pytest.fixture
def thermometer():
    return {
        "id": "dev-thermo-001",
        "name": "Termómetro Digital",
        "model": "T100",
        "mdr_class": "IIa",
        "mdr_classification_rule": "Rule 1",
        "risk_level": "low",
        "applicable_standards": [
            "ISO 80601-2-56:2017",  # Non-invasive thermometers
            "ISO 13485:2016",        # Medical devices QMS
            "ISO 14971:2019",        # Risk management
        ],
        "documentation_required": [
            "Technical File",
            "Risk Management Report",
            "Quality Management System",
        ],
    }

@pytest.fixture
def sphygmomanometer():
    return {
        "id": "dev-bp-001",
        "name": "Medidor de Tensão Arterial",
        "model": "BP-Plus",
        "mdr_class": "IIb",
        "mdr_classification_rule": "Rule 2",
        "risk_level": "medium",
        "applicable_standards": [
            "ISO 80601-2-30:2019",   # Non-invasive BP measurement
            "ISO 13485:2016",
            "ISO 14971:2019",
            "IEC 60601-1:2005",      # Medical electrical equipment general requirements
        ],
        "documentation_required": [
            "Technical File",
            "Risk Management Report",
            "Clinical Evaluation Report",
            "Quality Management System",
        ],
    }

@pytest.fixture
def glucometer():
    return {
        "id": "dev-gluco-001",
        "name": "Glicosímetro",
        "model": "GlucoFast",
        "mdr_class": "IIa",
        "mdr_classification_rule": "Rule 3",
        "risk_level": "low",
        "applicable_standards": [
            "ISO 15197:2013",        # Point-of-care glucose measurement
            "ISO 13485:2016",
            "ISO 14971:2019",
        ],
        "documentation_required": [
            "Technical File",
            "Risk Management Report",
            "Quality Management System",
            "Post-market surveillance plan",
        ],
    }

@pytest.fixture
def pulse_oximeter():
    return {
        "id": "dev-pox-001",
        "name": "Oxímetro de Pulso",
        "model": "OX-1",
        "mdr_class": "IIa",
        "mdr_classification_rule": "Rule 4",
        "risk_level": "low",
        "applicable_standards": [
            "ISO 80601-2-61:2017",   # Pulse oximeters
            "ISO 13485:2016",
            "ISO 14971:2019",
            "IEC 60601-1:2005",
        ],
        "documentation_required": [
            "Technical File",
            "Risk Management Report",
            "Quality Management System",
        ],
    }

# Testes de conformidade regulatória
def _test_mdr_classification(device):
    """Valida classificação MDR do dispositivo."""
    valid_classes = ["Class I", "IIa", "IIb", "III"]
    assert device["mdr_class"] in valid_classes, (
        f"Classe MDR '{device['mdr_class']}' inválida. "
        f"Deve ser uma de: {valid_classes}"
    )

def _test_mdr_rule_assigned(device):
    """Verifica se regra MDR foi atribuída."""
    assert device.get("mdr_classification_rule"), (
        "Regra de classificação MDR não definida. "
        "Ref: MDR Annex VIII (Rules for classification)"
    )

def _test_risk_level_defined(device):
    """Valida nível de risco."""
    valid_risks = ["low", "medium", "high", "critical"]
    assert device.get("risk_level") in valid_risks, (
        f"Nível de risco '{device.get('risk_level')}' inválido. "
        f"Deve ser uma de: {valid_risks}"
    )

def _test_applicable_standards(device):
    """Verifica se normas ISO/IEC foram identificadas."""
    standards = device.get("applicable_standards", [])
    assert isinstance(standards, list), "Normas devem ser lista"
    assert len(standards) > 0, (
        "Nenhuma norma aplicável identificada. "
        "Ref: ISO 13485, ISO 14971, ISO 80601-* conforme o tipo"
    )
    # Verifica que ISO 13485 está sempre presente (QMS obrigatório)
    assert any("13485" in s for s in standards), (
        "ISO 13485:2016 (Quality Management System) é obrigatória para todos os dispositivos"
    )

def _test_documentation_requirements(device):
    """Verifica se documentação regulatória foi identificada."""
    docs = device.get("documentation_required", [])
    assert isinstance(docs, list), "Documentação deve ser lista"
    assert len(docs) > 0, (
        "Nenhum requisito de documentação identificado. "
        "Ref: MDR Article 2 (Medical Device Definition)"
    )
    # Documentos obrigatórios para qualquer classe > I
    required_base = ["Technical File", "Risk Management Report"]
    for req in required_base:
        assert any(req.lower() in d.lower() for d in docs), (
            f"'{req}' é documentação obrigatória conforme MDR"
        )

# Testes parametrizados por dispositivo
@pytest.mark.parametrize(
    "device_fixture",
    ["thermometer", "sphygmomanometer", "glucometer", "pulse_oximeter"],
)
def test_mdr_classification(request, device_fixture):
    """Teste 1: Classificação MDR válida."""
    device = request.getfixturevalue(device_fixture)
    _test_mdr_classification(device)

@pytest.mark.parametrize(
    "device_fixture",
    ["thermometer", "sphygmomanometer", "glucometer", "pulse_oximeter"],
)
def test_mdr_rule_assigned(request, device_fixture):
    """Teste 2: Regra MDR definida."""
    device = request.getfixturevalue(device_fixture)
    _test_mdr_rule_assigned(device)

@pytest.mark.parametrize(
    "device_fixture",
    ["thermometer", "sphygmomanometer", "glucometer", "pulse_oximeter"],
)
def test_risk_level(request, device_fixture):
    """Teste 3: Nível de risco definido."""
    device = request.getfixturevalue(device_fixture)
    _test_risk_level_defined(device)

@pytest.mark.parametrize(
    "device_fixture",
    ["thermometer", "sphygmomanometer", "glucometer", "pulse_oximeter"],
)
def test_applicable_standards(request, device_fixture):
    """Teste 4: Normas ISO/IEC aplicáveis identificadas."""
    device = request.getfixturevalue(device_fixture)
    _test_applicable_standards(device)

@pytest.mark.parametrize(
    "device_fixture",
    ["thermometer", "sphygmomanometer", "glucometer", "pulse_oximeter"],
)
def test_documentation_requirements(request, device_fixture):
    """Teste 5: Requisitos de documentação regulatória definidos."""
    device = request.getfixturevalue(device_fixture)
    _test_documentation_requirements(device)
