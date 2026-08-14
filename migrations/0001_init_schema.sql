IF OBJECT_ID('HUBMAIL_Accounts', 'U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_Accounts (
        AccountID INT IDENTITY(1,1) PRIMARY KEY,
        UserID INT NOT NULL,
        EmailAddress NVARCHAR(255) NOT NULL,
        DisplayName NVARCHAR(200) NULL,
        IMAPHost NVARCHAR(255) NOT NULL,
        IMAPPort INT NOT NULL,
        SMTPHost NVARCHAR(255) NOT NULL,
        SMTPPort INT NOT NULL,
        Username NVARCHAR(255) NOT NULL,
        PasswordEnc NVARCHAR(MAX) NOT NULL,
        SignatureHtml NVARCHAR(MAX) NULL,
        IsDefault BIT NOT NULL DEFAULT 0,
        CreatedAt DATETIME DEFAULT GETDATE(),
        CONSTRAINT UQ_HUBMAIL_Accounts UNIQUE (UserID, EmailAddress)
    );
    CREATE INDEX IX_HUBMAIL_Accounts_User ON HUBMAIL_Accounts (UserID);
END;

IF OBJECT_ID('HUBMAIL_Contacts', 'U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_Contacts (
        ContactID INT IDENTITY(1,1) PRIMARY KEY,
        Name NVARCHAR(200) NOT NULL,
        Email NVARCHAR(255) NOT NULL,
        Phone NVARCHAR(50) NULL,
        Notes NVARCHAR(500) NULL,
        CreatedBy INT NULL,
        CreatedAt DATETIME DEFAULT GETDATE(),
        CONSTRAINT UQ_HUBMAIL_Contacts_Email UNIQUE (Email)
    );
END;

IF OBJECT_ID('HUBMAIL_Unread', 'U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_Unread (
        AccountID INT NOT NULL PRIMARY KEY,
        LastCheck DATETIME NULL,
        UnreadCount INT NOT NULL DEFAULT 0
    );
END;