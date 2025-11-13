/*
 ****************************************************************************
 *
 * nefencode.c - NEF Lossless Compression Encoding Logic
 * Copyright (c) 2025, Horshack
 *
 */

//
// header files
//
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>

//#define F_DEBUG

//
// macros
//
#define MIN(a, b)       ((a)<(b) ? (a) : (b))
#define MAX(a, b)       ((a)>(b) ? (a) : (b))
#define COUNTOF(x)      ((sizeof((x))) / sizeof((x)[0]))
#define FALSE           (0)
#define TRUE            (1)
#define BYTES_IN_MB     (1048576)

#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    #define SWAP_ENDIAN_32_BITS_IF_PLATFORM_LITTLE_ENDIAN(value) (uint32_t)__builtin_bswap32((uint32_t)(value))
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
    #define SWAP_ENDIAN_32_BITS_IF_PLATFORM_LITTLE_ENDIAN(value) (value)
#else
    #error Endianness of platform cant be determined
#endif


//
// types
//
typedef int BOOL;
typedef struct _NEF_HUFF_TABLE_ENTRY {
    int     countBitsNeededForDeltaPixelValue_IncludingSign;
    int     countHuffEncodingBits;
    uint8_t huffEncodingValue;
} NEF_HUFF_TABLE_ENTRY;

typedef struct _NEF_ENCODE_CONTEXT {
    int         outputBufferBytesStored;
    int         countBitsValidInCurrentBitWord;
    uint32_t    currentBitWord;
    uint8_t     *outputBuffer;
} NEF_ENCODE_CONTEXT;

typedef struct _NEF_ENCODE_PARAMS {
    int         countColumns;
    int         countRows;
    int         sourceBufferSizeBytes;
    int         outputBufferSizeBytes;
    uint16_t    startingPredictiveValue;
    uint16_t    pad1;
    void        *sourceData;
    void        *outputBuffer;
} NEF_ENCODE_PARAMS;

typedef enum {
    NEF_ENCODE_ERROR_SOURCE_BUFFER_TOO_SMALL    = -1,
    NEF_ENCODE_ERROR_NO_HUFF_TABLE_ENTRY        = -2,   // occurs when source data is > 14-bits
    NEF_ENCODE_ERROR_OUTPUT_BUFFER_TOO_SMALL    = -3,
} t_NefEncodeError;


/**
 *
 * Returns the highest bit set in a value, or -1 if value is zero
 * @param value Value to find MSB
 * @returns Highest bit set in value, or -1 if value is zero
 */
static inline int findMsbSet(uint32_t value) {
    if (value != 0) {
        int countLeadingZeros = __builtin_clz(value);
        return (sizeof(uint32_t) * CHAR_BIT - 1) - countLeadingZeros;
    }
    return -1;
}


/**
 *
 * Calculates the number of bits required to represent a value
 * @param value Value to calculate # bits required to represent
 * @returns Number of bits required to represent value
 */
static inline int calcBitsNeedForValue(uint32_t value) {
    int highestBitSet = findMsbSet((uint32_t)value);
    return highestBitSet != -1 ? highestBitSet : 0;
}


/**
 *
 * Returns Huffman encoding information for a pixel delta value requiring a specified number of bits
 * @param numDeltaPixelValueBitsNeeded Number of bits in pixel delta value that need to be encoded
 * @returns Pointer to a NEF_HUFF_TABLE_ENTRY entry. If there is no huffman
 * entry associated with 'numDeltaPixelValueBitsNeeded' then NULL is returned
 */
static inline const NEF_HUFF_TABLE_ENTRY *getHuffTableEntryForCountBitsNeededEncodeDeltaPixelValue(int numDeltaPixelValueBitsNeeded) {

    static NEF_HUFF_TABLE_ENTRY entries[] = {

            {   7,      2,  0x00  },    // entry #00 - delta values requiring 7 bits to represent.  Uses 2-bits of huff-encoding, huff-encoded ID = 0x00

            {   6,      3,  0x02  },    // entry #01 - delta values requiring 6 bits to represent.  Uses 3-bits of huff-encoding, huff-encoded ID = 0x02
            {   8,      3,  0x03  },    // entry #02 - delta values requiring 8 bits to represent.  Uses 3-bits of huff-encoding, huff-encoded ID = 0x03
            {   5,      3,  0x04  },    // entry #03 - delta values requiring 5 bits to represent.  Uses 3-bits of huff-encoding, huff-encoded ID = 0x04
            {   9,      3,  0x05  },    // entry #04 - delta values requiring 9 bits to represent.  Uses 3-bits of huff-encoding, huff-encoded ID = 0x05

            {   4,      4,  0x0c  },    // entry #05 - delta values requiring 4 bits to represent.  Uses 4-bits of huff-encoding, huff-encoded ID = 0x0c
            {   10,     4,  0x0d  },    // entry #06 - delta values requiring 10 bits to represent. Uses 4-bits of huff-encoding, huff-encoded ID = 0x0c

            {   3,      5,  0x1c  },    // entry #07 - delta values requiring 3 bits to represent.  Uses 5-bits of huff-encoding, huff-encoded ID = 0x1c
            {   11,     5,  0x1d  },    // entry #08 - delta values requiring 11 bits to represent. Uses 5-bits of huff-encoding, huff-encoded ID = 0x1d

            {   12,     6,  0x3c  },    // entry #09 - delta values requiring 12 bits to represent. Uses 6-bits of huff-encoding, huff-encoded ID = 0x3c
            {    2,     6,  0x3d  },    // entry #10 - delta values requiring 2 bits to represent.  Uses 6-bits of huff-encoding, huff-encoded ID = 0x3d
            {    0,     6,  0x3e  },    // entry #11 - delta values requiring 0 bits to represent.  Uses 6-bits of huff-encoding, huff-encoded ID = 0x3f

            {    1,     7,  0x7e  },    // entry #12 - delta values requiring 1 bits to represent.  Uses 7-bits of huff-encoding, huff-encoded ID = 0x7e

            {    13,    8,  0xfe  },    // entry #13 - delta values requiring 13 bits to represent. Uses 8-bits of huff-encoding, huff-encoded ID = 0xfe
            {    14,    8,  0xff  },    // entry #14 - delta values requiring 14 bits to represent. Uses 8-bits of huff-encoding, huff-encoded ID = 0xff
    };
    static NEF_HUFF_TABLE_ENTRY *numBitsNeededToHuffTableEntry[] = {
        &entries[11],   // 0 bits needed  -> entry #11
        &entries[12],   // 1 bits needed  -> entry #12
        &entries[10],   // 2 bits needed  -> entry #10
        &entries[7],    // 3 bits needed  -> entry #7
        &entries[5],    // 4 bits needed  -> entry #5
        &entries[3],    // 5 bits needed  -> entry #3
        &entries[1],    // 6 bits needed  -> entry #1
        &entries[0],    // 7 bits needed  -> entry #0
        &entries[2],    // 8 bits needed  -> entry #2
        &entries[4],    // 9 bits needed  -> entry #4
        &entries[6],    // 10 bits needed -> entry #6
        &entries[8],    // 11 bits needed -> entry #8
        &entries[9],    // 12 bits needed -> entry #9
        &entries[13],   // 13 bits needed -> entry #13
        &entries[14],   // 14 bits needed -> entry #14
    };
    if (numDeltaPixelValueBitsNeeded < COUNTOF(numBitsNeededToHuffTableEntry))
        return numBitsNeededToHuffTableEntry[numDeltaPixelValueBitsNeeded];
    return NULL;
}


/**
 *
 * Adds bits from passed value into encoded image output
 * @param i Image structure we're adding bits into
 * @param countBits Number of bits in 'value' to add.
 * @param value Value we're encoding
 */
static void addBitsToOutput(NEF_ENCODE_CONTEXT *ctx, int countBits, uint32_t value) {

    int countBitsLeftToAdd = countBits;
    int countBitsAddThisIteration;

    // assumed 'countBits < 32', as logic doesn't support shift operations == 32 bits, the behavior of which is undefined in 'C'
    while (countBitsLeftToAdd > 0) {

        countBitsAddThisIteration = MIN(countBitsLeftToAdd, 32 - ctx->countBitsValidInCurrentBitWord); // constrain this loop iteration to # bits left and #bits available in current bit word

        ctx->currentBitWord <<= countBitsAddThisIteration; // make room for bits being inserted
        ctx->currentBitWord |= value >> (countBitsLeftToAdd - countBitsAddThisIteration) & ((1 << countBitsAddThisIteration) - 1); // insert bits

        ctx->countBitsValidInCurrentBitWord += countBitsAddThisIteration;

        if (ctx->countBitsValidInCurrentBitWord == 32) {
            *(uint32_t *)&ctx->outputBuffer[ctx->outputBufferBytesStored] = SWAP_ENDIAN_32_BITS_IF_PLATFORM_LITTLE_ENDIAN(ctx->currentBitWord);
            ctx->outputBufferBytesStored += 4;
            ctx->countBitsValidInCurrentBitWord = 0;
            ctx->currentBitWord = 0x00;
        }

        countBitsLeftToAdd -= countBitsAddThisIteration;
    }
}


/**
 *
 * Writes any bits pending in the current bitword from previous invocation(s) of addBitsToOutput()
 * @param i Image structure we're flushing
 */
static void flushBitsToOutput(NEF_ENCODE_CONTEXT *ctx) {

    int countPadBitsToFillWord;

    if (ctx->countBitsValidInCurrentBitWord > 0) {
        countPadBitsToFillWord = 32 - ctx->countBitsValidInCurrentBitWord;
        addBitsToOutput(ctx, countPadBitsToFillWord, 0x00000000);
        ctx->outputBufferBytesStored -= countPadBitsToFillWord / 8; // only count actual data we flushed, excluding bytes we used only to pad to a full 32-bit word
    }
}



/**
 *
 * Encodes bayer pixel data into Nikon's proprietary NEF lossless compression
 * @param params Input parameters
 * @param Number of encoded bytes stored in output, or < 0 with t_NefEncodeError result
 */
t_NefEncodeError NefEncode(NEF_ENCODE_PARAMS *params) {

    int         countBitsNeededForDeltaValue;
    int         row, column, sourceDataIndex, outputBufferBytesAvail;
    BOOL        fNegativeDeltaValue;
    uint16_t    pixelValue, prevPixelValue;
    uint16_t    deltaPixelValue, encodedDeltaPixelValueWithSignBit, deltaPixelValueSigned;
    uint16_t    prevPixelValuesRows[2][2], prevPixelValuesThisRow[2];
    uint16_t    *sourceData;
    const NEF_HUFF_TABLE_ENTRY  *huffTableEntry;
    NEF_ENCODE_CONTEXT          ctx;

#if F_DEBUG
    printf (">> NefEncode() called\n");
    printf("&params = %p\n", params);
    printf("  .countColumns = %d\n", params->countColumns);
    printf("  .countRows = %d\n", params->countRows);
    printf("  .sourceBufferSizeBytes = %d\n", params->sourceBufferSizeBytes);
    printf("  .outputBufferSizeBytes = %d\n", params->outputBufferSizeBytes);
    printf("  .startingPredictiveValue = %d\n", params->startingPredictiveValue);
    printf("  .pad1 = %d\n", params->pad1);
    printf("  .sourceData = %p\n", params->sourceData);
    uint16_t *p = (uint16_t *)params->sourceData;
    printf("       = %04x %04x %04x %04x\n", p[0], p[1], p[2], p[3]);
    printf("  .outputBuffer = %p\n", params->outputBuffer);
    printf("\n");
#endif

    //
    // Nikon's lossless compression stores a delta value for each pixel, which starts from
    // a per-channel seed value (0x800). The data for each pixel is stored in <length><data>
    // form, where <length> is a Huffman-encoded bit length and <data> is a delta value
    // to apply to the running/previous pixel value. The Huffman codes are optimized to
    // represent the more-common delta bit lengths with the fewest number of bits for the
    // Huffman code
    //

    if (params->sourceBufferSizeBytes < params->countRows*params->countColumns * sizeof(uint16_t))
        return NEF_ENCODE_ERROR_SOURCE_BUFFER_TOO_SMALL;

    memset(&ctx, 0, sizeof(ctx));
    ctx.outputBuffer = params->outputBuffer;

    prevPixelValuesThisRow[0] = prevPixelValuesThisRow[1] = params->startingPredictiveValue;
    prevPixelValuesRows[0][0] = prevPixelValuesRows[0][1] = prevPixelValuesRows[1][0] = prevPixelValuesRows[1][1] = params->startingPredictiveValue;

    sourceDataIndex = 0;
    sourceData = (uint16_t *)params->sourceData;

    for (row = 0; row < params->countRows; row++) {

        outputBufferBytesAvail = params->outputBufferSizeBytes - ctx.outputBufferBytesStored;
        if (outputBufferBytesAvail < BYTES_IN_MB)
            return NEF_ENCODE_ERROR_OUTPUT_BUFFER_TOO_SMALL;

        for (column = 0; column < params->countColumns; column++) {

            pixelValue = sourceData[sourceDataIndex++];

            if (column <= 1)
                // first pixel of this channel for this row. seed using the running/previous pixel value for this row
                prevPixelValue = prevPixelValuesRows[row & 1][column];
            else
                // use the previous pixel value
                prevPixelValue = prevPixelValuesThisRow[column & 1];

            // calculate delta pixel value for this next pixel, including handling the negative delta value case
            if (pixelValue >= prevPixelValue) {
                fNegativeDeltaValue = FALSE;
                deltaPixelValue = pixelValue - prevPixelValue;
            } else {
                fNegativeDeltaValue = TRUE;
                deltaPixelValue = prevPixelValue - pixelValue;
            }

            // calculate the #bits needed to represent this delta value
            if (deltaPixelValue != 0)
                countBitsNeededForDeltaValue = calcBitsNeedForValue((uint32_t)deltaPixelValue) + 1 /* +1 for sign bit */;
            else
                countBitsNeededForDeltaValue = 0;

            // get the Huff table info to encode this bit length
            huffTableEntry = getHuffTableEntryForCountBitsNeededEncodeDeltaPixelValue(countBitsNeededForDeltaValue);
            if (huffTableEntry == NULL)
                return NEF_ENCODE_ERROR_NO_HUFF_TABLE_ENTRY;

            // build the pixel value with the sign bit encoded
            if (!fNegativeDeltaValue) {
                deltaPixelValueSigned = deltaPixelValue;
                encodedDeltaPixelValueWithSignBit = deltaPixelValue;
            } else {
                encodedDeltaPixelValueWithSignBit = ((1 << countBitsNeededForDeltaValue) - 1) - deltaPixelValue;
                deltaPixelValueSigned = -deltaPixelValue;
            }

            // save the running/previous pixel value to be used for next pixel. also handle the initial seed case for each row
            if (column <= 1)
                prevPixelValuesThisRow[column] = prevPixelValuesRows[row & 1][column] += deltaPixelValueSigned;
            else
                prevPixelValuesThisRow[column & 1] += deltaPixelValueSigned;

            // pack the huffman-encoded length and pixel delta value into our output buffer
            addBitsToOutput(&ctx, huffTableEntry->countHuffEncodingBits, (uint32_t)huffTableEntry->huffEncodingValue);
            addBitsToOutput(&ctx, countBitsNeededForDeltaValue, (uint32_t)encodedDeltaPixelValueWithSignBit);

        }
    }

    // flush out any remaining partial data
    flushBitsToOutput(&ctx);
    return ctx.outputBufferBytesStored;
}
