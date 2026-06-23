import os
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
CORS(app)

# Configure Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# This serves your HTML file!
@app.route('/')
def home():
    return render_template('index.html')

# This handles the AI requests
@app.route('/api/chat', methods=['POST'])
def handle_chat():
    request_data = request.json
    user_prompt = request_data.get("message", "")
    
    if not user_prompt:
        return jsonify({"error": "No message provided"}), 400
        
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(user_prompt)
        return jsonify({"reply": response.text})
        
    except Exception as error:
        return jsonify({"error": str(error)}), 500

if __name__ == '__main__':
    server_port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=server_port)