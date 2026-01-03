from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    
    # Load config
    app.config.from_object('app.config.Config')
    
    # Initialize extensions
    db.init_app(app)
    CORS(app)
    
    # Register blueprints
    from app.routes.pesajes import pesajes_bp
    from app.routes.balanza import balanza_bp
    
    app.register_blueprint(pesajes_bp, url_prefix='/api/pesajes')
    app.register_blueprint(balanza_bp, url_prefix='/api/balanza')
    
    # Create tables
    with app.app_context():
        db.create_all()
    
    return app
