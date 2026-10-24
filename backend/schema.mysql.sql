CREATE TABLE IF NOT EXISTS tracks (
  id VARCHAR(64) PRIMARY KEY,
  original_name TEXT NOT NULL,
  state VARCHAR(24) NOT NULL,
  decision VARCHAR(16),
  audio_hash VARCHAR(64),
  similarity_score DOUBLE,
  ai_job_id VARCHAR(64),
  result_json LONGTEXT,
  error TEXT,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS provenance_events (
  track_id VARCHAR(64) PRIMARY KEY,
  manifest_hash VARCHAR(64) NOT NULL,
  manifest_json LONGTEXT NOT NULL,
  creator_wallet VARCHAR(256),
  creator_signature TEXT,
  created_at VARCHAR(40) NOT NULL,
  FOREIGN KEY(track_id) REFERENCES tracks(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS contributors (
  track_id VARCHAR(64) NOT NULL,
  wallet_address VARCHAR(256) NOT NULL,
  share_bps INT NOT NULL,
  signature TEXT,
  created_at VARCHAR(40) NOT NULL,
  PRIMARY KEY(track_id,wallet_address),
  FOREIGN KEY(track_id) REFERENCES tracks(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reviews (
  id VARCHAR(64) PRIMARY KEY,
  track_id VARCHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  reviewer_wallet VARCHAR(256),
  note TEXT,
  created_at VARCHAR(40) NOT NULL,
  FOREIGN KEY(track_id) REFERENCES tracks(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS settlements (
  id VARCHAR(64) PRIMARY KEY,
  track_id VARCHAR(64) NOT NULL,
  gross_amount VARCHAR(128) NOT NULL,
  fee_bps INT NOT NULL,
  net_amount VARCHAR(128) NOT NULL,
  status VARCHAR(24) NOT NULL,
  transaction_hash VARCHAR(256),
  created_at VARCHAR(40) NOT NULL,
  FOREIGN KEY(track_id) REFERENCES tracks(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
