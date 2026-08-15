IF OBJECT_ID('HUBMAIL_UserSettings','U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_UserSettings (
        UserID INT NOT NULL PRIMARY KEY,
        DisplayName NVARCHAR(120) NULL,
        Phone NVARCHAR(50) NULL,
        SignatureHtml NVARCHAR(MAX) NULL
    );
END
