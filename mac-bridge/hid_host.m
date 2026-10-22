// SPDX-License-Identifier: Apache-2.0
#import <Foundation/Foundation.h>
#import <IOKit/hidsystem/IOHIDUserDevice.h>
#import <IOKit/hid/IOHIDKeys.h>
#import <mach/mach_time.h>
#import <dispatch/dispatch.h>
#import <unistd.h>

static IOHIDUserDeviceRef device;
static dispatch_queue_t hidQueue;
static int exitCode;
static NSString *serialNumber;
static BOOL published;
static BOOL activated;
static const uint8_t descriptor[] = {
    0x06, 0xd0, 0xf1, 0x09, 0x01, 0xa1, 0x01,
    0x09, 0x20, 0x15, 0x00, 0x26, 0xff, 0x00,
    0x75, 0x08, 0x95, 0x40, 0x81, 0x02,
    0x09, 0x21, 0x15, 0x00, 0x26, 0xff, 0x00,
    0x75, 0x08, 0x95, 0x40, 0x91, 0x02, 0xc0
};

static void event(NSDictionary *message) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:message options:0 error:nil];
    if (!data) { return; }
    fwrite(data.bytes, 1, data.length, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static void finish(int result) {
    exitCode = result;
    if (!activated) { CFRelease(device); exit(result); }
    IOHIDUserDeviceCancel(device);
}

static void checkPublication(unsigned attempt, BOOL probe) {
    NSMutableDictionary *matching = CFBridgingRelease(IOServiceMatching("IOHIDDevice"));
    matching[@"IOPropertyMatch"] = @{@kIOHIDSerialNumberKey: serialNumber};
    io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault,
                                        (__bridge_retained CFDictionaryRef)matching);
    if (service) {
        uint64_t registryID = 0;
        IORegistryEntryGetRegistryEntryID(service, &registryID);
        IOObjectRelease(service);
        published = YES;
        event(@{@"event": @"ready", @"usage_page": @0xf1d0,
                @"report_size": @64, @"registry_id": @(registryID)});
        if (probe) {
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), hidQueue, ^{ finish(0); });
        }
    } else if (attempt >= 30) {
        event(@{@"event": @"error", @"reason": @"virtual_hid_not_published"});
        finish(3);
    } else {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 10), hidQueue,
                       ^{ checkPublication(attempt + 1, probe); });
    }
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        BOOL probe = argc == 2 && strcmp(argv[1], "--probe") == 0;
        if (argc > 1 && !probe) { fprintf(stderr, "Usage: hid_host [--probe]\n"); return 2; }
        serialNumber = [@"diy-fido-" stringByAppendingString:NSUUID.UUID.UUIDString];
        NSDictionary *properties = @{
            @kIOHIDReportDescriptorKey: [NSData dataWithBytes:descriptor length:sizeof(descriptor)],
            @kIOHIDVendorIDKey: @0xaaaa, @kIOHIDProductIDKey: @0xf1d0,
            @kIOHIDPrimaryUsagePageKey: @0xf1d0, @kIOHIDPrimaryUsageKey: @1,
            @kIOHIDTransportKey: @"USB", @kIOHIDProductKey: @"DIY FIDO BLE bridge",
            @kIOHIDManufacturerKey: @"DIY prototype",
            @kIOHIDSerialNumberKey: serialNumber
        };
        device = IOHIDUserDeviceCreateWithProperties(kCFAllocatorDefault,
                    (__bridge CFDictionaryRef)properties, IOHIDUserDeviceOptionsCreateOnActivate);
        if (!device) {
            event(@{@"event": @"error", @"reason": @"virtual_hid_creation_denied",
                @"required_entitlement": @"com.apple.developer.hid.virtual.device"});
            return 3;
        }
        hidQueue = dispatch_queue_create("diy.fido.hid", DISPATCH_QUEUE_SERIAL);
        IOHIDUserDeviceSetDispatchQueue(device, hidQueue);
        IOHIDUserDeviceRegisterSetReportBlock(device,
            ^IOReturn(IOHIDReportType type, uint32_t reportID, const uint8_t *report, CFIndex length) {
                if (!published) { return kIOReturnNotReady; }
                if (type != kIOHIDReportTypeOutput || reportID != 0 || length != 64) {
                    return kIOReturnBadArgument;
                }
                NSData *data = [NSData dataWithBytes:report length:64];
                event(@{@"event": @"output", @"data": [data base64EncodedStringWithOptions:0]});
                return kIOReturnSuccess;
            });
        IOHIDUserDeviceRegisterGetReportBlock(device,
            ^IOReturn(IOHIDReportType type, uint32_t reportID, uint8_t *report, CFIndex *length) {
                return kIOReturnUnsupported;
            });
        IOHIDUserDeviceSetCancelHandler(device, ^{ CFRelease(device); exit(exitCode); });
        dispatch_async(hidQueue, ^{
            if (probe) {
                activated = YES;
                IOHIDUserDeviceActivate(device);
                checkPublication(0, YES);
            } else {
                event(@{@"event": @"prepared"});
            }
        });
        if (!probe) {
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
                @autoreleasepool {
                    // Bounded JSON lines: only 64-byte input reports cross this pipe.
                    char line[512];
                    while (fgets(line, sizeof(line), stdin)) {
                        @autoreleasepool {
                            if (!strchr(line, '\n')) {
                                int c; while ((c = getchar()) != '\n' && c != EOF) {}
                                dispatch_async(hidQueue, ^{ event(@{@"event": @"error", @"reason": @"invalid_line"}); });
                                continue;
                            }
                            NSData *json = [[NSString stringWithUTF8String:line] dataUsingEncoding:NSUTF8StringEncoding];
                            id parsed = json ? [NSJSONSerialization JSONObjectWithData:json options:0 error:nil] : nil;
                            if ([parsed isKindOfClass:NSDictionary.class] && [parsed[@"activate"] isEqual:@YES]) {
                                dispatch_async(hidQueue, ^{
                                    if (!activated) {
                                        activated = YES;
                                        IOHIDUserDeviceActivate(device);
                                        checkPublication(0, NO);
                                    }
                                });
                                continue;
                            }
                            NSString *encoded = [parsed isKindOfClass:NSDictionary.class] ? parsed[@"input"] : nil;
                            NSData *report = [encoded isKindOfClass:NSString.class] ?
                                [[NSData alloc] initWithBase64EncodedString:encoded options:0] : nil;
                            if (report.length != 64) {
                                dispatch_async(hidQueue, ^{ event(@{@"event": @"error", @"reason": @"invalid_report"}); });
                                continue;
                            }
                            dispatch_async(hidQueue, ^{
                                IOReturn result = IOHIDUserDeviceHandleReportWithTimeStamp(device,
                                                    mach_absolute_time(), report.bytes, report.length);
                                if (result != kIOReturnSuccess) {
                                    event(@{@"event": @"error", @"reason": @"input_report_failed", @"status": @(result)});
                                }
                            });
                        }
                    }
                    dispatch_async(hidQueue, ^{ finish(0); });
                }
            });
        }
    }
    dispatch_main();
}
