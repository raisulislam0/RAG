import json
from evaluate import load
from numpy import average

# Load metrics
bleu     = load("bleu")
rouge    = load("rouge")
bertscore= load("bertscore")

# # Load your data
with open("responses_n3.json", "r", encoding="utf-8") as f:
    data = json.load(f)


refs = [d["reference"] for d in data]
cands= [d["candidate"] for d in data]

# Compute BLEU (needs List[List[str]] for references)
bleu_res = bleu.compute(
    predictions=cands,
    references=[[r] for r in refs]
)
print("BLEU:", bleu_res["bleu"])

# Compute ROUGE (one-to-one)
rouge_res = rouge.compute(predictions=cands, references=refs)
print("ROUGE-L:", rouge_res["rougeL"])

# Compute BERTScore (one-to-one)
bertscore_res = bertscore.compute(predictions=cands, references=refs, lang="en")
print("BERTScore F1 (mean):", sum(bertscore_res["f1"]) / len(bertscore_res["f1"]))


predictions = []
references = []

for response in data:
    predictions.append(response['candidate'])
    references.append(response['prompt'])

results = bertscore.compute(predictions=predictions, references=references, model_type="distilbert-base-uncased")

for key in results.keys():
    if key == 'hashcode':
        continue 
    print(f"{key}: {average(results[key])}")
    

