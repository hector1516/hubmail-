IF OBJECT_ID('HUBMAIL_SyncState', 'U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_SyncState (
        AccountID INT NOT NULL,
        Folder NVARCHAR(500) NOT NULL,
        LastSync DATETIME NULL,
        TotalCount INT NOT NULL DEFAULT 0,
        CONSTRAINT PK_HUBMAIL_SyncState PRIMARY KEY (AccountID, Folder)
    );
END;

IF OBJECT_ID('HUBMAIL_Messages', 'U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_Messages (
        MsgID BIGINT IDENTITY(1,1) PRIMARY KEY,
        AccountID INT NOT NULL,
        Folder NVARCHAR(500) NOT NULL,
        UID BIGINT NOT NULL,
        MessageIdHeader NVARCHAR(500) NULL,
        InReplyTo NVARCHAR(500) NULL,
        FromName NVARCHAR(500) NULL,
        FromEmail NVARCHAR(500) NULL,
        ToText NVARCHAR(2000) NULL,
        CcText NVARCHAR(2000) NULL,
        Subject NVARCHAR(1000) NULL,
        DateSent DATETIME NULL,
        Seen BIT NOT NULL DEFAULT 0,
        Answered BIT NOT NULL DEFAULT 0,
        Flagged BIT NOT NULL DEFAULT 0,
        Deleted BIT NOT NULL DEFAULT 0,
        Draft BIT NOT NULL DEFAULT 0,
        HasAttachments BIT NOT NULL DEFAULT 0,
        BodyHtml NVARCHAR(MAX) NULL,
        BodyText NVARCHAR(MAX) NULL,
        Size INT NOT NULL DEFAULT 0,
        SyncedAt DATETIME NOT NULL DEFAULT GETDATE(),
        CONSTRAINT UQ_HUBMAIL_Messages_UID UNIQUE (AccountID, Folder, UID)
    );
    CREATE INDEX IX_HUBMAIL_Messages_List ON HUBMAIL_Messages (AccountID, Folder, DateSent DESC);
    CREATE INDEX IX_HUBMAIL_Messages_Unread ON HUBMAIL_Messages (AccountID, Folder, Seen);
END;