from transformers import BartForConditionalGeneration, BartTokenizer
import torch

tokenizer = BartTokenizer.from_pretrained("facebook/bart-large-cnn")
model = BartForConditionalGeneration.from_pretrained("facebook/bart-large-cnn")

device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)
model.eval()

def summarize(article):
    inputs = tokenizer(
        article,
        return_tensors="pt",
        max_length=1024,
        truncation=True
    ).to(device)

    with torch.no_grad():
        summary_ids = model.generate(
            inputs["input_ids"],
            num_beams=6,
            max_length=120,
            min_length=60,
            no_repeat_ngram_size=3,
            length_penalty=1.5,
            early_stopping=True
        )

    return tokenizer.decode(summary_ids[0], skip_special_tokens=True)
