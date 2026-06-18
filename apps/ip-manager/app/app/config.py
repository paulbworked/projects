import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    # Read from App Service application settings
    SQL_SERVER   = os.environ.get("AZURE_SQL_SERVER")
    SQL_DATABASE = os.environ.get("AZURE_SQL_DATABASE")

    # Managed Identity connection string — no password required
    SQLALCHEMY_DATABASE_URI = (
        f"mssql+pyodbc://{SQL_SERVER}/{SQL_DATABASE}"
        f"?driver=ODBC+Driver+18+for+SQL+Server"
        f"&authentication=ActiveDirectoryMsi"
        f"&encrypt=yes"
        f"&TrustServerCertificate=no"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
