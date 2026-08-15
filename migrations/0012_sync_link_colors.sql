UPDATE l
SET l.Color = m.Color
FROM HUBMAIL_Accounts l
JOIN HUBMAIL_Accounts m ON m.AccountID = l.CanonicalAccountID
WHERE l.CanonicalAccountID IS NOT NULL AND ISNULL(l.Color,'') <> ISNULL(m.Color,'');