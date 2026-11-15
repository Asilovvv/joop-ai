import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../bloc/bookings_bloc.dart';
import '../bloc/summary_cubit.dart';
import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// «Предоплата получена»: staff saw the money; the customer is told in their chat where the channel allows it.
Future<void> markDepositPaid(BuildContext context, Booking booking) async {
  final messenger = ScaffoldMessenger.of(context);
  final bookings = context.read<BookingsBloc>();
  final summary = context.read<SummaryCubit>();
  String text;
  try {
    final (updated, told) = await context.read<JoopRepository>().depositPaid(booking.id);
    bookings.add(BookingUpdated(updated));
    text = told ? S.current.depositToldCustomer : S.current.depositTellYourself;
  } on ApiException catch (e) {
    text = e.message; // marked a moment ago, or released by its deadline
    bookings.add(const BookingsPolled());
  }
  summary.load();
  messenger
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));
}
