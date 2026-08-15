IF OBJECT_ID('HUBMAIL_Attachments','U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_Attachments (
        AttachID BIGINT IDENTITY(1,1) PRIMARY KEY,
        AccountID INT NOT NULL,
        Folder NVARCHAR(500) NOT NULL,
        UID BIGINT NOT NULL,
        Name NVARCHAR(500) NULL,
        ContentType NVARCHAR(200) NULL,
        Cid NVARCHAR(500) NULL,
        Size INT NOT NULL DEFAULT 0,
        Data VARBINARY(MAX) NULL,
        SyncedAt DATETIME NOT NULL DEFAULT GETDATE()
    );
    CREATE INDEX IX_HUBMAIL_Attachments_Msg ON HUBMAIL_Attachments (AccountID, Folder, UID);
END;

IF OBJECT_ID('HUBMAIL_Folders','U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_Folders (
        AccountID INT NOT NULL,
        Folder NVARCHAR(500) NOT NULL,
        Delimiter NVARCHAR(10) NULL,
        Flags NVARCHAR(500) NULL,
        SyncedAt DATETIME NOT NULL DEFAULT GETDATE(),
        CONSTRAINT PK_HUBMAIL_Folders PRIMARY KEY (AccountID, Folder)
    );
END;