from rag_router_utils import analyze_question

questions = [
    "Quais são as obrigações gerais de um fabricante segundo o MDR?",
    "Em relação à primeira pergunta indica então 10 obrigações que um fabricante tem segundo o MDR",
    "Que documentação técnica tenho de preparar para um dispositivo médico segundo o MDR?",
    "Quais são os passos do procedimento de avaliação da conformidade?",
    "Que obrigações tem um organismo notificado segundo o MDR?",
]

for q in questions:
    print("\nQ:", q)
    print(analyze_question(q))