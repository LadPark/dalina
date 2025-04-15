from flask import Flask, render_template, request
import pandas as pd
import os

app = Flask(__name__)

data_path = "data"

@app.route("/")
def index():
    events = [d for d in os.listdir(data_path) if os.path.isdir(os.path.join(data_path, d))]
    return render_template("index.html", events=events)

@app.route("/search", methods=["POST"])
def search():
    event = request.form["event"]
    keyword = request.form["bib"].strip().upper()
    csv_path = os.path.join(data_path, event, "results.csv")

    if not os.path.exists(csv_path):
        return render_template("results.html", keyword=keyword, results=[], event=event, link=None)

    df = pd.read_csv(csv_path)
    matches = df[df["배번"].str.contains(keyword, na=False)]

    link_path = os.path.join(data_path, event, "onedrive_link.txt")
    gallery_link = open(link_path).read().strip() if os.path.exists(link_path) else None

    return render_template("results.html", keyword=keyword, results=matches.values.tolist(), event=event, link=gallery_link)

if __name__ == "__main__":
    app.run(debug=True)
