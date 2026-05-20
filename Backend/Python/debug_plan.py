from rag_router_utils import analyze_question

questions = [
    "Que obrigações tem o prestador de um sistema de IA de risco elevado segundo o AI Act?",
    "Esse software com IA para interpretar ECG é considerado de alto risco no AI Act?",
    "Preciso de organismo notificado para um dispositivo Classe I?",
    "Que requisitos gerais de segurança e desempenho tenho de cumprir segundo o MDR?",
]

for q in questions:
    print("\nQ:", q)
    print(analyze_question(q))