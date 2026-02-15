import torch
from transformers import RobertaTokenizer, RobertaForSequenceClassification

MODEL_NAME = "roberta-base"

tokenizer = None
model = None

def load_model():
    global tokenizer, model

    tokenizer = RobertaTokenizer.from_pretrained(MODEL_NAME)
    model = RobertaForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=3
    )

    model.eval()

def predict(text: str):
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True
    )

    with torch.no_grad():
        outputs = model(**inputs)

    probs = torch.softmax(outputs.logits, dim=1)
    prediction = torch.argmax(probs, dim=1).item()

    return {
        "label": prediction,
        "probabilities": probs.tolist()[0]
    }
