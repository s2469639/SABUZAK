from flask import Flask, render_template, request
from dotenv import load_dotenv
from retail_research import analyze_retail_market

load_dotenv()
app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        product_name = request.form.get("product_name", "")
        country = request.form.get("country", "")
        strengths = request.form.get("strengths", "")
        raw_materials = request.form.get("raw_materials", "")
        certifications = request.form.get("certifications", "")
        target_price = request.form.get("target_price", "")
        retail_data = analyze_retail_market(product_name, country, strengths, raw_materials, target_price)
        return render_template("index.html", retail=retail_data, submitted=True, inputs={"product_name": product_name, "country": country, "strengths": strengths, "raw_materials": raw_materials, "certifications": certifications, "target_price": target_price})
    return render_template("index.html", submitted=False)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
