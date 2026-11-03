export type AiDecision = 'PASS' | 'WARN' | 'HOLD' | 'BLOCK';

export type RegistrationPolicy = {
  issueRegistrationSignature: boolean;
  allowRegisterAndMint: boolean;
  isHold: boolean;
};

export function registrationPolicy(decision: AiDecision): RegistrationPolicy {
  if (decision === 'BLOCK') {
    return { issueRegistrationSignature: false, allowRegisterAndMint: false, isHold: false };
  }
  return {
    issueRegistrationSignature: true,
    allowRegisterAndMint: true,
    isHold: decision === 'HOLD',
  };
}

export type Eip712Registration = {
  trackId: string;
  audioHash: string;
  manifestHash: string;
  policyVersion: string;
  similarityScore: number | null;
  isHold: boolean;
};

export function buildRegistrationPayload(
  decision: AiDecision,
  payload: Omit<Eip712Registration, 'isHold'>,
): Eip712Registration {
  return { ...payload, isHold: registrationPolicy(decision).isHold };
}
