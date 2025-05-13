try:
    from app import app
except Exception as e:
    import os
    import traceback
    from flask import Flask, jsonify, send_from_directory

    error_message = str(e)
    traceback_info = traceback.format_exc()
    print(f"Error importing main app: {error_message}")
    print(f"Traceback: {traceback_info}")
    print("Creating minimal fallback app")

    app = Flask(__name__, static_folder='static')


    @app.route('/')
    def home():
        return f"App encountered error: {error_message}<br><pre>{traceback_info}</pre>"


    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                   'favicon.ico', mimetype='image/vnd.microsoft.icon')


    @app.route('/healthz')
    def health():
        return jsonify({"status": "error", "error": error_message, "traceback": traceback_info}), 200

if __name__ == "__main__":
    app.run()