-- Cambiar las columnas Folder a collation case-sensitive (utf8mb4_bin)
-- para permitir carpetas IMAP que difieren solo en mayusculas (ej. INBOX/Temporal vs INBOX/temporal)
-- y mantener consistencia entre tablas en JOINs/comparaciones.
ALTER TABLE HUBMAIL_Folders MODIFY Folder VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE HUBMAIL_Messages MODIFY Folder VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE HUBMAIL_SyncState MODIFY Folder VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE HUBMAIL_Attachments MODIFY Folder VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;