from app import create_app

def init():
    app = create_app(start_workers=False)
    print(
        "BBDD validada. Schema v"
        f"{app.config.get('SCHEMA_VERSION', 'no-versionado')}."
    )

if __name__ == '__main__':
    init()
