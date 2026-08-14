IF COL_LENGTH('dbo.HUBMAIL_Accounts', 'CanonicalAccountID') IS NULL
BEGIN
    ALTER TABLE HUBMAIL_Accounts ADD CanonicalAccountID INT NULL;
END;