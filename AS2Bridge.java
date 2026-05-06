import de.mendelson.comm.as2.log.LogEntry;
import de.mendelson.comm.as2.message.AS2MessageInfo;
import de.mendelson.comm.as2.message.AS2Payload;
import de.mendelson.comm.as2.message.MessageOverviewFilter;
import de.mendelson.comm.as2.message.clientserver.*;
import de.mendelson.comm.as2.partner.Partner;
import de.mendelson.comm.as2.partner.clientserver.PartnerListRequest;
import de.mendelson.comm.as2.partner.clientserver.PartnerListResponse;
import de.mendelson.util.clientserver.messages.*;
import de.mendelson.util.clientserver.clients.datatransfer.DownloadRequestFile;
import de.mendelson.util.clientserver.clients.datatransfer.DownloadResponseFile;

import javax.net.ssl.*;
import java.io.*;
import java.math.BigInteger;
import java.security.cert.X509Certificate;
import java.util.Arrays;
import java.util.zip.*;

/**
 * Thin Java bridge: receives a command via CLI args, talks to the Mendelson AS2
 * server using the real serialized protocol, writes JSON to stdout.
 *
 * Usage: java AS2Bridge <host> <port> <user> <password> <command> [args...]
 * Commands: ping | list_partners | list_messages [limit [direction [startMs [endMs]]]]
 *           | get_message_log <messageId> | get_message_payload <messageId>
 */
public class AS2Bridge {

    private static SSLSocket sock;
    private static OutputStream out;
    private static InputStream  in;

    public static void main(String[] args) throws Exception {
        if (args.length < 5) {
            System.err.println("Usage: AS2Bridge <host> <port> <user> <password> <command> [args...]");
            System.exit(1);
        }
        String host     = args[0];
        int    port     = Integer.parseInt(args[1]);
        String user     = args[2];
        String password = args[3];
        String command  = args[4];

        connect(host, port);
        login(user, password);

        switch (command) {
            case "ping":
                System.out.println("{\"status\":\"ok\"}");
                break;
            case "list_partners":
                listPartners();
                break;
            case "list_messages": {
                int  limit        = args.length > 5  ? Integer.parseInt(args[5])  : 50;
                int  direction    = args.length > 6  ? Integer.parseInt(args[6])  : 0;
                long startMs      = args.length > 7  ? Long.parseLong(args[7])    : 0L;
                long endMs        = args.length > 8  ? Long.parseLong(args[8])    : 0L;
                boolean finished  = args.length > 9  ? Boolean.parseBoolean(args[9])  : true;
                boolean pending   = args.length > 10 ? Boolean.parseBoolean(args[10]) : true;
                boolean stopped   = args.length > 11 ? Boolean.parseBoolean(args[11]) : true;
                int  messageType  = args.length > 12 ? Integer.parseInt(args[12]) : 0;
                listMessages(limit, direction, startMs, endMs, finished, pending, stopped, messageType);
                break;
            }
            case "get_message_log":
                getMessageLog(args[5]);
                break;
            case "get_message_payload":
                getMessagePayload(args[5]);
                break;
            case "download_payload":
                downloadPayload(args[5]);
                break;
            default:
                System.err.println("Unknown command: " + command);
                System.exit(1);
        }

        quit(user);
        sock.close();
    }

    // -----------------------------------------------------------------------
    // Connection & auth
    // -----------------------------------------------------------------------

    static void connect(String host, int port) throws Exception {
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(null, new TrustManager[]{new X509TrustManager() {
            public void checkClientTrusted(X509Certificate[] c, String a) {}
            public void checkServerTrusted(X509Certificate[] c, String a) {}
            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
        }}, new java.security.SecureRandom());

        SSLSocketFactory f = ctx.getSocketFactory();
        sock = (SSLSocket) f.createSocket(host, port);
        sock.startHandshake();
        out = sock.getOutputStream();
        in  = sock.getInputStream();

        readObject(); // ServerInfo
        readObject(); // LoginRequired
    }

    static void login(String user, String password) throws Exception {
        LoginRequest req = new LoginRequest(1);
        req.setUserName(user);
        req.setPasswd(password.toCharArray());
        req.setClientId("mendelson AS2 2024 build 598");
        sendObject(req);
        LoginState state = (LoginState) readObject();
        if (state.getState() != LoginState.STATE_AUTHENTICATION_SUCCESS) {
            throw new Exception("Login failed (state=" + state.getState() + "): " + state.getStateDetails());
        }
    }

    static void quit(String user) throws Exception {
        QuitRequest q = new QuitRequest();
        q.setUser(user);
        sendObject(q);
    }

    // -----------------------------------------------------------------------
    // Commands
    // -----------------------------------------------------------------------

    static void listPartners() throws Exception {
        PartnerListRequest req = new PartnerListRequest(PartnerListRequest.LIST_ALL);
        sendObject(req);
        PartnerListResponse resp = (PartnerListResponse) readObject();
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (Partner p : resp.getList()) {
            if (!first) sb.append(",");
            first = false;
            sb.append(partnerToJson(p));
        }
        sb.append("]");
        System.out.println("{\"partners\":" + sb + "}");
    }

    static void listMessages(int limit, int direction, long startMs, long endMs,
                             boolean finished, boolean pending, boolean stopped, int messageType) throws Exception {
        MessageOverviewFilter filter = new MessageOverviewFilter();
        filter.setLimit(limit);
        filter.setShowDirection(direction);
        filter.setShowFinished(finished);
        filter.setShowPending(pending);
        filter.setShowStopped(stopped);
        if (startMs > 0) filter.setStartTime(startMs);
        if (endMs   > 0) filter.setEndTime(endMs);
        filter.setShowMessageType(messageType);

        MessageOverviewRequest req = new MessageOverviewRequest(filter);
        sendObject(req);
        MessageOverviewResponse resp = (MessageOverviewResponse) readObject();
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (AS2MessageInfo m : resp.getList()) {
            if (!first) sb.append(",");
            first = false;
            sb.append(messageInfoToJson(m));
        }
        sb.append("]");
        System.out.println("{\"messages\":" + sb + ",\"total\":" + resp.getMessageSumOnServer() + "}");
    }

    static void getMessageLog(String messageId) throws Exception {
        MessageLogRequest req = new MessageLogRequest(messageId);
        sendObject(req);
        MessageLogResponse resp = (MessageLogResponse) readObject();
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (LogEntry e : resp.getList()) {
            if (!first) sb.append(",");
            first = false;
            sb.append("{\"level\":").append(jsonStr(e.getLevel() != null ? e.getLevel().getName() : null))
              .append(",\"time\":").append(e.getMillis())
              .append(",\"message\":").append(jsonStr(e.getMessage()))
              .append("}");
        }
        sb.append("]");
        System.out.println("{\"log\":" + sb + "}");
    }

    static void getMessagePayload(String messageId) throws Exception {
        MessagePayloadRequest req = new MessagePayloadRequest(messageId);
        sendObject(req);
        MessagePayloadResponse resp = (MessagePayloadResponse) readObject();
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (AS2Payload p : resp.getList()) {
            if (!first) sb.append(",");
            first = false;
            sb.append("{\"originalFilename\":").append(jsonStr(p.getOriginalFilename()))
              .append(",\"payloadFilename\":").append(jsonStr(p.getPayloadFilename()))
              .append(",\"contentType\":").append(jsonStr(p.getContentType()))
              .append("}");
        }
        sb.append("]");
        System.out.println("{\"payloads\":" + sb + "}");
    }

    static void downloadPayload(String messageId) throws Exception {
        // First get the payload metadata to obtain the server-side file path
        MessagePayloadRequest req = new MessagePayloadRequest(messageId);
        sendObject(req);
        MessagePayloadResponse resp = (MessagePayloadResponse) readObject();
        if (resp.getList() == null || resp.getList().isEmpty()) {
            System.err.println("No payload found for message: " + messageId);
            System.exit(1);
        }
        AS2Payload p = resp.getList().get(0);

        // Now download the actual file bytes using the server-side path
        DownloadRequestFile dlReq = new DownloadRequestFile();
        dlReq.setFilename(p.getPayloadFilename());
        sendObject(dlReq);
        DownloadResponseFile dlResp = (DownloadResponseFile) readObject();
        if (dlResp.getException() != null) {
            throw new Exception("Server error: " + dlResp.getException().getClass().getName() + ": " + dlResp.getException().getMessage());
        }

        // Write metadata as a single header line to stderr, raw bytes to stdout
        System.err.println("CONTENT_TYPE:" + (p.getContentType() != null ? p.getContentType() : "application/octet-stream"));
        System.err.println("ORIGINAL_FILENAME:" + (p.getOriginalFilename() != null ? p.getOriginalFilename() : "payload"));
        byte[] data = dlResp.getDataBytes();
        System.out.write(data);
        System.out.flush();
    }

    // -----------------------------------------------------------------------
    // Transport — matches codec A.java (decoder) and B.java (encoder) exactly
    // -----------------------------------------------------------------------

    static void sendObject(Object obj) throws Exception {
        // Serialize to bytes
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        ObjectOutputStream oos = new ObjectOutputStream(baos);
        oos.writeObject(obj);
        oos.flush();
        byte[] serialized = baos.toByteArray();

        // Deflate at level 1 (matches B.java: deflater.setLevel(1))
        Deflater deflater = new Deflater();
        deflater.setLevel(1);
        deflater.setInput(serialized);
        deflater.finish();
        ByteArrayOutputStream compressed = new ByteArrayOutputStream(serialized.length);
        byte[] buf = new byte[1024];
        while (!deflater.finished()) {
            compressed.write(buf, 0, deflater.deflate(buf));
        }
        deflater.end();
        byte[] payload = compressed.toByteArray();

        // 4-byte length prefix via BigInteger (matches B.java exactly)
        byte[] lenBytes = new byte[4];
        Arrays.fill(lenBytes, (byte) 0);
        byte[] bigIntBytes = BigInteger.valueOf(payload.length).toByteArray();
        System.arraycopy(bigIntBytes, 0, lenBytes, lenBytes.length - bigIntBytes.length, bigIntBytes.length);

        out.write(lenBytes);
        out.write(payload);
        out.flush();
    }

    static Object readObject() throws Exception {
        // The server may push ServerLogMessage frames at any time before the
        // real response. Keep reading until we get a non-log message.
        while (true) {
            byte[] lenBytes = new byte[4];
            int r = 0;
            while (r < 4) r += in.read(lenBytes, r, 4 - r);
            int length = new BigInteger(lenBytes).intValue();

            byte[] payload = new byte[length];
            r = 0;
            while (r < length) r += in.read(payload, r, length - r);

            Inflater inflater = new Inflater();
            inflater.setInput(payload);
            ByteArrayOutputStream decompressed = new ByteArrayOutputStream();
            byte[] buf = new byte[1024];
            while (!inflater.finished()) {
                decompressed.write(buf, 0, inflater.inflate(buf));
            }
            inflater.end();

            ObjectInputStream ois = new ObjectInputStream(
                new ByteArrayInputStream(decompressed.toByteArray()));
            Object obj = ois.readObject();
            if (obj instanceof ServerLogMessage) continue;
            return obj;
        }
    }

    // -----------------------------------------------------------------------
    // JSON helpers
    // -----------------------------------------------------------------------

    static String jsonStr(String s) {
        if (s == null) return "null";
        return "\"" + s.replace("\\", "\\\\")
                       .replace("\"", "\\\"")
                       .replace("\n", "\\n")
                       .replace("\r", "\\r")
                       .replace("\t", "\\t") + "\"";
    }

    static String partnerToJson(Partner p) {
        return "{" +
            "\"name\":"          + jsonStr(p.getName())                    + "," +
            "\"as2ident\":"      + jsonStr(p.getAS2Identification())       + "," +
            "\"localstation\":"  + p.isLocalStation()                      + "," +
            "\"url\":"           + jsonStr(p.getURL())                     + "," +
            "\"mdnurl\":"        + jsonStr(p.getMdnURL())                  + "," +
            "\"email\":"         + jsonStr(p.getEmail())                   + "," +
            "\"subject\":"       + jsonStr(p.getSubject())                 + "," +
            "\"contenttype\":"   + jsonStr(p.getContentType())             + "," +
            "\"signtype\":"      + p.getSignType()                         + "," +
            "\"encryptiontype\":" + p.getEncryptionType()                  + "," +
            "\"compression\":"   + p.getCompressionType()                  + "," +
            "\"signedmdn\":"     + p.isSignedMDN()                        + "," +
            "\"syncmdn\":"       + p.isSyncMDN()                          + "," +
            "\"keepfilename\":"  + p.getKeepOriginalFilenameOnReceipt()   + "," +
            "\"enabledirpoll\":" + p.isEnableDirPoll()                    + "," +
            "\"pollinterval\":"  + p.getPollInterval()                    +
        "}";
    }

    static String messageInfoToJson(AS2MessageInfo m) {
        long initDate = m.getInitDate() != null ? m.getInitDate().getTime() : -1;
        return "{" +
            "\"messageid\":"      + jsonStr(m.getMessageId())     + "," +
            "\"userdefinedid\":"  + jsonStr(m.getUserdefinedId()) + "," +
            "\"senderid\":"       + jsonStr(m.getSenderId())      + "," +
            "\"receiverid\":"     + jsonStr(m.getReceiverId())    + "," +
            "\"state\":"          + m.getState()                  + "," +
            "\"direction\":"      + m.getDirection()              + "," +
            "\"signtype\":"       + m.getSignType()               + "," +
            "\"encryptiontype\":" + m.getEncryptionType()         + "," +
            "\"compression\":"    + m.getCompressionType()        + "," +
            "\"usestls\":"        + m.usesTLS()                   + "," +
            "\"initdate\":"       + initDate                      + "," +
            "\"subject\":"        + jsonStr(m.getSubject())       +
        "}";
    }
}
