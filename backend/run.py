from app import create_app, socketio
from app.config import Config

app = create_app()

if __name__ == '__main__':
    socketio.run(
        app,
        host='127.0.0.1',
        port=Config.API_PORT,
        debug=Config.DEBUG,
        use_reloader=Config.DEBUG,
        allow_unsafe_werkzeug=True
    )
