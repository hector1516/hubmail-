IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('HUBMAIL_Accounts') AND name='Color')
    ALTER TABLE HUBMAIL_Accounts ADD Color NVARCHAR(20) NULL;

IF COL_LENGTH('dbo.HUBMAIL_Accounts', 'Color') IS NOT NULL
EXEC('UPDATE HUBMAIL_Accounts SET Color =
    CASE AccountID % 12
        WHEN 0 THEN ''#2a6fd6''
        WHEN 1 THEN ''#8e44ad''
        WHEN 2 THEN ''#d63031''
        WHEN 3 THEN ''#0984e3''
        WHEN 4 THEN ''#00b894''
        WHEN 5 THEN ''#e17055''
        WHEN 6 THEN ''#e84393''
        WHEN 7 THEN ''#6c5ce7''
        WHEN 8 THEN ''#00cec9''
        WHEN 9 THEN ''#e67e22''
        WHEN 10 THEN ''#d35400''
        ELSE ''#16a085''
    END
WHERE Color IS NULL;');