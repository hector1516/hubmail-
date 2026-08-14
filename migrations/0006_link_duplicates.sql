UPDATE HUBMAIL_Accounts SET CanonicalAccountID = NULL;

WITH Counts AS (
    SELECT a.AccountID, a.EmailAddress, COUNT(m.MsgID) AS N
    FROM HUBMAIL_Accounts a
    LEFT JOIN HUBMAIL_Messages m ON m.AccountID = a.AccountID
    GROUP BY a.AccountID, a.EmailAddress
),
Ranked AS (
    SELECT AccountID, EmailAddress,
           ROW_NUMBER() OVER (PARTITION BY EmailAddress ORDER BY N DESC, AccountID) AS rn
    FROM Counts
)
UPDATE A
SET CanonicalAccountID = R.AccountID
FROM HUBMAIL_Accounts A
INNER JOIN Ranked R ON R.EmailAddress = A.EmailAddress AND R.rn = 1 AND R.AccountID <> A.AccountID;

DELETE FROM HUBMAIL_Messages WHERE AccountID IN (SELECT AccountID FROM HUBMAIL_Accounts WHERE CanonicalAccountID IS NOT NULL);
DELETE FROM HUBMAIL_SyncState WHERE AccountID IN (SELECT AccountID FROM HUBMAIL_Accounts WHERE CanonicalAccountID IS NOT NULL);