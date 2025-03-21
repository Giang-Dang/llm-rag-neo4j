from neo4j import GraphDatabase
import ollama
import medspacy
from medspacy.ner import TargetMatcher, TargetRule

# Initialize Neo4j driver
neo4j_uri = "bolt://localhost:7687"
neo4j_username = "neo4j"
neo4j_password = "12345678"
driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_username, neo4j_password))

# Load NLP models
nlp = medspacy.load()
target_matcher = nlp.get_pipe("medspacy_target_matcher")

# Define diseases
disease_rules = [
    TargetRule("Influenza", "DISEASE"),
    TargetRule("Diabetes Mellitus", "DISEASE"),
    TargetRule("Hypertension", "DISEASE"),
    TargetRule("Asthma", "DISEASE"),
    TargetRule("Migraine", "DISEASE")
]

# Define symptoms
symptom_rules = [
    TargetRule("Fever", "SYMPTOM"),
    TargetRule("Cough", "SYMPTOM"),
    TargetRule("Fatigue", "SYMPTOM"),
    TargetRule("Shortness of Breath", "SYMPTOM"),
    TargetRule("Headache", "SYMPTOM"),
    TargetRule("Nausea", "SYMPTOM"),
    TargetRule("Dizziness", "SYMPTOM"),
    TargetRule("Chest Pain", "SYMPTOM"),
    TargetRule("Sweating", "SYMPTOM"),
    TargetRule("Blurred Vision", "SYMPTOM")
]

# Define preventions
prevention_rules = [
    TargetRule("Influenza Vaccination", "PREVENTION"),
    TargetRule("Healthy Diet and Weight Management", "PREVENTION"),
    TargetRule("Blood Pressure Monitoring and Low-Sodium Diet", "PREVENTION"),
    TargetRule("Avoid Allergens and Air Pollutants", "PREVENTION"),
    TargetRule("Regular Sleep and Stress Management", "PREVENTION")
]

# Define treatments
treatment_rules = [
    TargetRule("Antiviral Medications", "TREATMENT"),
    TargetRule("Oseltamivir", "TREATMENT"),
    TargetRule("Zanamivir", "TREATMENT"),
    TargetRule("Insulin Therapy", "TREATMENT"),
    TargetRule("Oral Hypoglycemics", "TREATMENT"),
    TargetRule("Antihypertensive Medications", "TREATMENT"),
    TargetRule("ACE Inhibitors", "TREATMENT"),
    TargetRule("Beta-Blockers", "TREATMENT"),
    TargetRule("Bronchodilators", "TREATMENT"),
    TargetRule("Inhaled Corticosteroids", "TREATMENT"),
    TargetRule("Analgesics", "TREATMENT"),
    TargetRule("NSAIDs", "TREATMENT"),
    TargetRule("Triptans", "TREATMENT")
]

# Combine all rules
all_rules = disease_rules + symptom_rules + prevention_rules + treatment_rules

# Add rules to the matcher
target_matcher.add(all_rules)


def extract_medical_entities(text):
    """Extract medical entities from text using medspaCy."""
    doc = nlp(text)
    entities = []
    for ent in doc.ents:
        entities.append({
            'entity': ent.text,
            'label': ent.label_
        })
    print(f'extract_medical_entities > results for {text} : {entities}')
    return entities


def verify_entity_relationship(entity1, entity2):
    """Verify if there's a relationship between two entities in the Neo4j database."""
    with driver.session() as session:
        result = session.run(
            "MATCH (s)-[r]->(o) "
            "WHERE toLower(s.name) = toLower($entity1) AND toLower(o.name) = toLower($entity2) "
            "RETURN s, r, o",
            entity1=entity1,
            entity2=entity2
        )
        return result.single() is not None


def analyze_question(question):
    """Analyze the question to identify entities and determine the type of medical information requested."""
    doc = nlp(question.lower())
    entities = [ent.text for ent in doc.ents]

    keywords_to_query_type = {
        "symptom": "symptoms",
        "treatment": "treatments",
        "treat": "treatments",
        "cause": "causes",
        "etiology": "causes",
        "prevention": "prevention",
        "prevent": "prevention"
    }

    query_type = "general"
    for keyword, q_type in keywords_to_query_type.items():
        if keyword in question:
            query_type = q_type
            break

    return entities, query_type


def fetch_context_from_neo4j(entities, query_type):
    """Fetch relevant context from Neo4j based on entities and query type."""
    query_templates = {
        "symptoms": """
            MATCH (d:Disease)
            WHERE toLower(d.name) = toLower($entity)
            OPTIONAL MATCH (d)-[:HAS_SYMPTOM]->(s:Symptom)
            RETURN d.name AS disease, collect(s.name) AS symptoms
        """,
        "treatments": """
            MATCH (d:Disease)
            WHERE toLower(d.name) = toLower($entity)
            OPTIONAL MATCH (d)-[:HAS_TREATMENT]->(t:Treatment)
            RETURN d.name AS disease, collect(t.name) AS treatments
        """,
        "causes": """
            MATCH (d:Disease)
            WHERE toLower(d.name) = toLower($entity)
            OPTIONAL MATCH (d)-[:HAS_CAUSE]->(c:Cause)
            RETURN d.name AS disease, collect(c.name) AS causes
        """,
        "prevention": """
            MATCH (d:Disease)
            WHERE toLower(d.name) = toLower($entity)
            OPTIONAL MATCH (d)-[:HAS_PREVENTION]->(p:Prevention)
            RETURN d.name AS disease, collect(p.name) AS prevention_methods
        """,
        "general": """
            MATCH (d:Disease)
            WHERE toLower(d.name) = toLower($entity)
            OPTIONAL MATCH (d)-[r]-(n)
            RETURN d.name AS disease, type(r) AS relationship, collect(n.name) AS related_entities
        """
    }

    context = ""
    with driver.session() as session:
        for entity in entities:
            query = query_templates.get(query_type, query_templates["general"])
            result = session.run(query, entity=entity)
            for record in result:
                if query_type == "symptoms":
                    context += f"Disease: {record['disease']}\nSymptoms: {', '.join(record['symptoms'])}\n\n"
                elif query_type == "treatments":
                    context += f"Disease: {record['disease']}\nTreatments: {', '.join(record['treatments'])}\n\n"
                elif query_type == "causes":
                    context += f"Disease: {record['disease']}\nCauses: {', '.join(record['causes'])}\n\n"
                elif query_type == "prevention":
                    context += f"Disease: {record['disease']}\nPrevention Methods: {', '.join(record['prevention_methods'])}\n\n"
                else:
                    context += f"Disease: {record['disease']}\n{record['relationship'].replace('_', ' ').title()}: {', '.join(record['related_entities'])}\n\n"
    return context


def generate_response(question, use_graph=False):
    """Generate a response from the LLM, optionally using Neo4j for context."""
    if use_graph:
        entities, query_type = analyze_question(question)
        context = fetch_context_from_neo4j(entities, query_type)
        if context:
            question = f"{question}\n\nContext:\n{context}"

    response = ollama.generate(
        model="gemma3:4b",
        prompt=question
    )
    # Ensure we return a string rather than a response object
    if hasattr(response, "text"):
        return response.text
    else:
        return str(response)


def evaluate_factual_accuracy(response):
    """Evaluate the factual accuracy of a response by checking entities against the Neo4j database."""
    entities = extract_medical_entities(response)

    # Group entities by type
    entity_groups = {}
    for entity in entities:
        entity_type = entity['label']
        if entity_type not in entity_groups:
            entity_groups[entity_type] = []
        entity_groups[entity_type].append(entity['entity'])

    # Check relationships between entities
    verified_relationships = 0
    total_relationships = 0

    # Check disease-symptom relationships
    if 'DISEASE' in entity_groups and 'SYMPTOM' in entity_groups:
        for disease in entity_groups['DISEASE']:
            for symptom in entity_groups['SYMPTOM']:
                total_relationships += 1
                if verify_entity_relationship(disease, symptom):
                    verified_relationships += 1

    # Check disease-treatment relationships
    if 'DISEASE' in entity_groups and 'TREATMENT' in entity_groups:
        for disease in entity_groups['DISEASE']:
            for treatment in entity_groups['TREATMENT']:
                total_relationships += 1
                if verify_entity_relationship(disease, treatment):
                    verified_relationships += 1

    # Calculate accuracy
    accuracy = verified_relationships / \
        max(1, total_relationships)  # Avoid division by zero
    return accuracy


def evaluate_responses(questions):
    """Evaluate LLM responses with and without Neo4j integration for multiple questions.

    Args:
        questions: List of questions or single question string
    """
    # Convert single question to list if needed
    if isinstance(questions, str):
        questions = [questions]

    results = []

    for idx, question in enumerate(questions, 1):
        print(f"Processing question {idx}: {question}")
        prompt = f"Please provide a concise and accurate answer to the medical question below. If you lack sufficient information or are uncertain about the answer, please acknowledge this and refrain from providing an inaccurate response. Focus solely on addressing the question without including unrelated information.\n\nQuestion: {question}"

        # Generate responses
        response_without_graph = generate_response(prompt, use_graph=False)
        response_with_graph = generate_response(prompt, use_graph=True)

        # Evaluate factual accuracy
        accuracy_without_graph = evaluate_factual_accuracy(
            response_without_graph)
        accuracy_with_graph = evaluate_factual_accuracy(response_with_graph)

        results.append({
            "question": question,
            "response_without_graph": response_without_graph,
            "accuracy_without_graph": accuracy_without_graph,
            "response_with_graph": response_with_graph,
            "accuracy_with_graph": accuracy_with_graph
        })

    return results if len(results) > 1 else results[0]


def generate_report(evaluations, filename="report.md"):
    """Generate a Markdown report from the evaluation results with comparison tables."""
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("# Medical Evaluation Report\n\n")

        # Create accuracy comparison table header
        f.write("## Factual Accuracy Comparison\n\n")
        f.write("| Question | Without Neo4j | With Neo4j |\n")
        f.write("|----------|---------------|------------|\n")

        # Initialize totals
        total_without_db = 0
        total_with_db = 0
        question_count = len(evaluations) if isinstance(evaluations, list) else 1
        
        if isinstance(evaluations, list):
            # Multiple questions case
            for eval_item in evaluations:
                accuracy_without = eval_item["accuracy_without_graph"]
                accuracy_with = eval_item["accuracy_with_graph"]
                
                # Add to totals
                total_without_db += accuracy_without
                total_with_db += accuracy_with
                
                # Format accuracies as percentages
                accuracy_without_str = f"{accuracy_without:.2%}"
                accuracy_with_str = f"{accuracy_with:.2%}"
                
                # Write table row
                f.write(f"| {eval_item['question']} | {accuracy_without_str} | {accuracy_with_str} |\n")
        else:
            # Single question case
            accuracy_without = evaluations["accuracy_without_graph"]
            accuracy_with = evaluations["accuracy_with_graph"]
            
            # Add to totals
            total_without_db += accuracy_without
            total_with_db += accuracy_with
            
            # Format accuracies as percentages
            accuracy_without_str = f"{accuracy_without:.2%}"
            accuracy_with_str = f"{accuracy_with:.2%}"
            
            # Write table row
            f.write(f"| {evaluations['question']} | {accuracy_without_str} | {accuracy_with_str} |\n")

        # Calculate and write averages
        avg_without_db = total_without_db / question_count
        avg_with_db = total_with_db / question_count
        
        f.write("\n## Summary\n\n")
        f.write(f"Average Factual Accuracy without Neo4j: {avg_without_db:.2%}\n\n")
        f.write(f"Average Factual Accuracy with Neo4j: {avg_with_db:.2%}\n\n")
        f.write(f"Overall Improvement: {(avg_with_db - avg_without_db):.2%}\n\n")

        # Create response comparison table
        f.write("## Response Comparison\n\n")
        f.write("| Question | Response without Neo4j | Response with Neo4j |\n")
        f.write("|----------|----------------------|-------------------|\n")

        if isinstance(evaluations, list):
            for eval_item in evaluations:
                # Clean and format responses by replacing newlines and markdown content
                response_without = eval_item["response_without_graph"]
                response_with = eval_item["response_with_graph"]
                
                # Extract content between response=' and ' if present
                if "response='" in response_without:
                    response_without = response_without.split("response='")[1].split("'")[0]
                if "response='" in response_with:
                    response_with = response_with.split("response='")[1].split("'")[0]
                
                # Remove markdown formatting and clean up text
                response_without = response_without.replace("\n", " ").replace("*", "").replace("---", "")
                response_with = response_with.replace("\n", " ").replace("*", "").replace("---", "")
                
                # Write formatted row to markdown table
                f.write(f"| {eval_item['question']} | {response_without} | {response_with} |\n")
        else:
            # Handle single evaluation case
            response_without = evaluations["response_without_graph"]
            response_with = evaluations["response_with_graph"]
            
            # Extract content between response=' and ' if present
            if "response='" in response_without:
                response_without = response_without.split("response='")[1].split("'")[0]
            if "response='" in response_with:
                response_with = response_with.split("response='")[1].split("'")[0]
            
            # Clean and format responses
            response_without = response_without.replace("\n", " ").replace("*", "").replace("---", "")
            response_with = response_with.replace("\n", " ").replace("*", "").replace("---", "")
            
            # Write formatted row to markdown table
            f.write(f"| {evaluations['question']} | {response_without} | {response_with} |\n")


# Example usage
sample_questions = [
    "What are the symptoms of Influenza?",
    "What treatments are available for Diabetes?",
    "What prevention methods are available for Asthma?",
    "What symptoms are associated with Hypertension?",
    "Which diseases have Fever as a symptom?",
    "What treatments does Migraine have?",
    "How can Influenza be prevented?",
    "List the symptoms of Diabetes.",
    "Find diseases that have Cough as a symptom.",
    "What prevention methods does Diabetes have?",
    "What is the treatment for Asthma?",
    "Which disease uses Vaccination as prevention?",
    "What symptoms does Asthma have?",
    "How many symptoms are linked to Influenza?",
    "Which diseases show Fatigue as a symptom?",
    "List all diseases with their symptoms.",
    "What is the prevention method for Migraine?",
    "What treatment is given for Hypertension?",
    "Find diseases that have Headache as a symptom.",
    "Which disease is linked to Nausea?",
    "List the treatments for Hypertension.",
    "What prevention methods are used for Influenza?",
    "What symptoms are related to Migraine?",
    "How is Diabetes treated?",
    "Which diseases are prevented by a Healthy Diet?",
    "List diseases that have Shortness of Breath as a symptom.",
    "What are the common symptoms of Asthma?",
    "Which diseases are linked to Cough and Fever?",
    "What treatment does Influenza have?",
    "What prevention is recommended for Hypertension?",
    "Which disease has the symptom Dizziness?",
    "List the treatments available for Migraine.",
    "What are the prevention methods for Diabetes?",
    "How many diseases have the symptom Chest Pain?",
    "Which diseases can be prevented by Regular Exercise?",
    "What symptom is most common in Influenza?",
    "Which diseases have Sweating as a symptom?"
]

# entities, query_type = analyze_question(question)
# context = fetch_context_from_neo4j(entities, query_type)
# print(context)
evaluation = evaluate_responses(sample_questions)
generate_report(evaluation)
print("Report generated as report.md")
