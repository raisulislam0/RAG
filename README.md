# Evaluation of Generated Response Against Gemini 2.5 Model

The json files contain Prompt, Reference (Gemini Response), and Candidate(llama3.2) response. 
Different mertics are used - BLEU, ROUGE, BERTSCORE, F1, etc.

*distilbert-base-uncased model captures both semantic and syntactic information about words, making it useful for various NLP task*

To evaluate load the json that contains responses to be tested. *with open("data.json", "r", encoding= "utf-8") as f:*

