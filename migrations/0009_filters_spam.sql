IF OBJECT_ID('HUBMAIL_Admins','U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_Admins (UserID INT NOT NULL PRIMARY KEY);
    INSERT INTO HUBMAIL_Admins (UserID)
    SELECT TOP 1 Id FROM HUB_Users WHERE LOWER(Email)=LOWER('it@ecc-sa.com.mx');
END

IF OBJECT_ID('HUBMAIL_SpamLists','U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_SpamLists (
        ListId INT IDENTITY(1,1) PRIMARY KEY,
        Name NVARCHAR(100) NOT NULL,
        Type NVARCHAR(10) NOT NULL DEFAULT 'DNSBL',
        Zone NVARCHAR(150) NOT NULL,
        Enabled BIT NOT NULL DEFAULT 1,
        Priority INT NOT NULL DEFAULT 0
    );
    INSERT INTO HUBMAIL_SpamLists (Name, Type, Zone, Enabled, Priority) VALUES
      ('Spamhaus ZEN', 'DNSBL', 'zen.spamhaus.org', 1, 0),
      ('SpamCop', 'DNSBL', 'bl.spamcop.net', 0, 1),
      ('Barracuda', 'DNSBL', 'b.barracudacentral.org', 0, 2),
      ('SORBS', 'DNSBL', 'dnsbl.sorbs.net', 0, 3);
END

IF OBJECT_ID('HUBMAIL_Filters','U') IS NULL
BEGIN
    CREATE TABLE HUBMAIL_Filters (
        FilterID INT IDENTITY(1,1) PRIMARY KEY,
        UserID INT NOT NULL,
        Scope NVARCHAR(10) NOT NULL DEFAULT 'ACCOUNT',
        AccountID INT NULL,
        Name NVARCHAR(100) NOT NULL,
        Conditions NVARCHAR(MAX) NOT NULL,
        Action NVARCHAR(20) NOT NULL,
        ActionFolder NVARCHAR(255) NULL,
        Enabled BIT NOT NULL DEFAULT 1,
        OrderNo INT NOT NULL DEFAULT 0
    );
END

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('HUBMAIL_Messages') AND name='Spam')
    ALTER TABLE HUBMAIL_Messages ADD Spam BIT NOT NULL DEFAULT 0;
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('HUBMAIL_Messages') AND name='SenderIP')
    ALTER TABLE HUBMAIL_Messages ADD SenderIP NVARCHAR(64) NULL;

IF EXISTS (SELECT 1 FROM HUBMAIL_Admins)
BEGIN
    INSERT INTO HUBMAIL_Accounts
        (UserID, EmailAddress, DisplayName, IMAPHost, IMAPPort, SMTPHost, SMTPPort, Username, PasswordEnc, SignatureHtml, Phone, IsDefault, CanonicalAccountID)
    SELECT adm.UserID, a.EmailAddress, a.DisplayName, a.IMAPHost, a.IMAPPort, a.SMTPHost, a.SMTPPort, a.Username, a.PasswordEnc, NULL, NULL, 0, ISNULL(a.CanonicalAccountID, a.AccountID)
    FROM HUBMAIL_Admins adm
    CROSS JOIN HUBMAIL_Accounts a
    WHERE NOT EXISTS (
        SELECT 1 FROM HUBMAIL_Accounts x
        WHERE x.UserID=adm.UserID AND x.EmailAddress=a.EmailAddress
          AND x.IMAPHost=a.IMAPHost AND x.Username=a.Username
    );
END