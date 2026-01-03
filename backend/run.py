from app import create_app
from app.config import Config

app = create_app()

if __name__ == '__main__':
    app.run(
        host='127.0.0.1',
        port=Config.API_PORT,
        debug=Config.DEBUG
    )
