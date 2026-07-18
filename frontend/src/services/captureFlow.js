const clonePayload = (payload) => JSON.parse(JSON.stringify(payload));

export const createCaptureCoordinator = ({
  uuid = () => crypto.randomUUID(),
} = {}) => {
  let pendingSession = null;

  return {
    begin(payload) {
      if (!pendingSession) {
        pendingSession = Object.freeze({
          captureId: uuid(),
          payload: Object.freeze(clonePayload(payload)),
        });
      }
      return pendingSession;
    },

    complete(captureId) {
      if (pendingSession?.captureId === captureId) {
        pendingSession = null;
      }
    },
  };
};

export const submitCaptureAndPrint = async ({
  session,
  captureRequest,
  printRequest,
}) => {
  const captureResponse = await captureRequest(
    session.payload,
    session.captureId,
  );
  const captureData = captureResponse.data;

  try {
    const printResponse = await printRequest(session.captureId);
    const printData = printResponse.data;

    return {
      captureSaved: true,
      idempotentReplay: captureData.idempotent_replay,
      status: printData.status,
      printStatus: printData.status,
      pesaje: printData.pesaje || captureData.pesaje,
      attempt: printData.print_attempt,
    };
  } catch (error) {
    return {
      captureSaved: true,
      idempotentReplay: captureData.idempotent_replay,
      status: 'SAVED_PRINT_FAILED',
      printStatus: 'SAVED_PRINT_FAILED',
      pesaje: captureData.pesaje,
      printError: error,
    };
  }
};
