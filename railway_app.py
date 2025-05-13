from app import app
import os

if __name__ == '__main__':
    # Use PORT from environment or default to 5000
    port = int(os.getenv('PORT', 5000))
    print(f"Starting app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
