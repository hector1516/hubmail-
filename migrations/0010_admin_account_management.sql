DECLARE @adm INT = (SELECT TOP 1 UserID FROM HUBMAIL_Admins);

IF @adm IS NOT NULL
BEGIN
    -- 0) Capturar los dueños originales de las cuentas maestras
    --    antes de transferirlas al administrador.
    IF OBJECT_ID('tempdb..#orig_owners') IS NOT NULL DROP TABLE #orig_owners;
    SELECT AccountID, UserID INTO #orig_owners
    FROM HUBMAIL_Accounts WHERE CanonicalAccountID IS NULL;

    -- 1) Quitar los vínculos propios del admin que apuntan a cuentas
    --    maestras (el admin pasará a poseerlas directamente).
    DELETE FROM HUBMAIL_Accounts
    WHERE UserID = @adm AND CanonicalAccountID IS NOT NULL;

    -- 2) El admin pasa a ser el dueño de todas las cuentas maestras.
    UPDATE HUBMAIL_Accounts SET UserID = @adm WHERE CanonicalAccountID IS NULL;

    -- 3) Preservar el acceso de los dueños originales creando su vínculo.
    INSERT INTO HUBMAIL_Accounts
        (UserID, EmailAddress, DisplayName, IMAPHost, IMAPPort, SMTPHost, SMTPPort,
         Username, PasswordEnc, SignatureHtml, Phone, IsDefault, CanonicalAccountID)
    SELECT o.UserID, m.EmailAddress, m.DisplayName, m.IMAPHost, m.IMAPPort,
           m.SMTPHost, m.SMTPPort, m.Username, m.PasswordEnc, m.SignatureHtml,
           m.Phone, 0, m.AccountID
    FROM #orig_owners o
    JOIN HUBMAIL_Accounts m ON m.AccountID = o.AccountID
    WHERE o.UserID <> @adm
      AND NOT EXISTS (
          SELECT 1 FROM HUBMAIL_Accounts x
          WHERE x.UserID = o.UserID AND x.EmailAddress = m.EmailAddress
      );

    DROP TABLE #orig_owners;
END