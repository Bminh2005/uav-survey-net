#include "protocol_defs.h"
#include <lwip/sockets.h>

void header_to_network(MessageHeader *hdr)
{
    hdr->magic = htons(hdr->magic);
    hdr->payload_len = htonl(hdr->payload_len);
}

void header_to_host(MessageHeader *hdr)
{
    hdr->magic = ntohs(hdr->magic);
    hdr->payload_len = ntohl(hdr->payload_len);
}