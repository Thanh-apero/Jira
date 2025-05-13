try:
    from app import app
except Exception as e:
    import os
    from flask import Flask, jsonify

    # Create a minimal working app if the main app fails to load
    print(f"Error importing main app: {e}")
    print("Creating minimal fallback app")

    app = Flask(__name__, static_folder='static')


    @app.route('/')
    def home():
        return "App is starting up or encountered an error. Check logs for details."


    @app.route('/healthz')
    def health():
        return jsonify({"status": "starting", "error": str(e)}), 200

if __name__ == "__main__":
    app.run()