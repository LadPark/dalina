from flask import Flask, render_template, request
import pandas as pd

app = Flask(__name__)
data = pd.read_csv("results.csv")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search", methods=["POST"])
def search():
    keyword = request.form["bib"].strip().upper()
    matches = data[data["배번"].str.contains(keyword, na=False)]
    return render_template("results.html", keyword=keyword, results=matches.values.tolist())

if __name__ == "__main__":
    app.run(debug=True)
