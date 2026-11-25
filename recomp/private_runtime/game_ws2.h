
int private_ws2(Cpu *c, const char *fn) {
    if (!strcmp(fn, "accept")) fn = "#1";
    if (!strcmp(fn, "bind")) fn = "#2";
    if (!strcmp(fn, "closesocket")) fn = "#3";
    if (!strcmp(fn, "connect")) fn = "#4";
    if (!strcmp(fn, "getpeername")) fn = "#5";
    if (!strcmp(fn, "getsockname")) fn = "#6";
    if (!strcmp(fn, "getsockopt")) fn = "#7";
    if (!strcmp(fn, "htonl")) fn = "#8";
    if (!strcmp(fn, "htons")) fn = "#9";
    if (!strcmp(fn, "inet_ntoa")) fn = "#11";
    if (!strcmp(fn, "ioctlsocket")) fn = "#12";
    if (!strcmp(fn, "listen")) fn = "#13";
    if (!strcmp(fn, "ntohl")) fn = "#14";
    if (!strcmp(fn, "ntohs")) fn = "#15";
    if (!strcmp(fn, "recv")) fn = "#16";
    if (!strcmp(fn, "recvfrom")) fn = "#17";
    if (!strcmp(fn, "select")) fn = "#18";
    if (!strcmp(fn, "send")) fn = "#19";
    if (!strcmp(fn, "sendto")) fn = "#20";
    if (!strcmp(fn, "setsockopt")) fn = "#21";
    if (!strcmp(fn, "shutdown")) fn = "#22";
    if (!strcmp(fn, "socket")) fn = "#23";
    if (!strcmp(fn, "gethostbyaddr")) fn = "#51";
    if (!strcmp(fn, "gethostbyname")) fn = "#52";
    if (!strcmp(fn, "getprotobyname")) fn = "#53";
    if (!strcmp(fn, "getprotobynumber")) fn = "#54";
    if (!strcmp(fn, "getservbyname")) fn = "#55";
    if (!strcmp(fn, "getservbyport")) fn = "#56";
    if (!strcmp(fn, "gethostname")) fn = "#57";
    if (!strcmp(fn, "WSAGetLastError")) fn = "#111";
    if (!strcmp(fn, "WSASetLastError")) fn = "#112";
    if (!strcmp(fn, "WSAStartup")) fn = "#115";
    if (!strcmp(fn, "WSACleanup")) fn = "#116";
    if (!strcmp(fn, "__WSAFDIsSet")) fn = "#151";
    return win32_ws2(c, fn);
}
