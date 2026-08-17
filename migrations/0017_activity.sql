IF OBJECT_ID('HUBMAIL_ActivityLog','U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_ActivityLog (
        LogID BIGINT IDENTITY(1,1) PRIMARY KEY,
        AccountID INT NULL,
        UserID INT NOT NULL,
        UserName NVARCHAR(200) NULL,
        Action NVARCHAR(100) NOT NULL,
        Details NVARCHAR(1000) NULL,
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    );
    CREATE INDEX IX_HUBMAIL_ActivityLog_Acc ON HUBMAIL_ActivityLog (AccountID, CreatedAt DESC);
    CREATE INDEX IX_HUBMAIL_ActivityLog_User ON HUBMAIL_ActivityLog (UserID, CreatedAt DESC);
END;