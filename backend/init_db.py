from app import create_app, db

def init():
    # Bypass background sync thread by mocking it or just creating DB
    app = create_app()
    with app.app_context():
        db.create_all()
        print("BBDD creada exitosamente.")

if __name__ == '__main__':
    init()
