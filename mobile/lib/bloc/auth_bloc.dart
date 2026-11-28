import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

// ---------------------------------------------------------------- events

sealed class AuthEvent extends Equatable {
  const AuthEvent();

  @override
  List<Object?> get props => [];
}

/// The app started: try the token saved on the device.
final class AuthStarted extends AuthEvent {
  const AuthStarted();
}

/// Sign in with the panel's credentials: the company login and password, or a staff member's own login.
final class AuthLoginRequested extends AuthEvent {
  const AuthLoginRequested(this.company, this.password, {this.user = '', this.server});

  final String company;
  final String password;
  final String user;

  /// Another server address, set on the sign-in screen; null keeps the current one.
  final String? server;

  @override
  List<Object?> get props => [company, password, user, server];
}

/// A business just signed up in the app (the sign-up screen made the session itself).
final class AuthSignedUp extends AuthEvent {
  const AuthSignedUp(this.account);

  final Account account;

  @override
  List<Object?> get props => [account];
}

final class AuthLogoutRequested extends AuthEvent {
  const AuthLogoutRequested();
}

/// The app's language changed: the account's own words (the people screen's name) come again in it.
final class AuthRefreshed extends AuthEvent {
  const AuthRefreshed();
}

// ---------------------------------------------------------------- states

sealed class AuthState extends Equatable {
  const AuthState();

  @override
  List<Object?> get props => [];
}

final class AuthInitial extends AuthState {
  const AuthInitial();
}

final class AuthLoading extends AuthState {
  const AuthLoading();
}

final class AuthSignedIn extends AuthState {
  const AuthSignedIn(this.account);

  final Account account;

  @override
  List<Object?> get props => [account];
}

final class AuthSignedOut extends AuthState {
  const AuthSignedOut({this.error});

  final String? error;

  @override
  List<Object?> get props => [error];
}

// ------------------------------------------------------------------ bloc

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  AuthBloc(this._repository) : super(const AuthInitial()) {
    on<AuthStarted>(_onStarted);
    on<AuthLoginRequested>(_onLogin);
    on<AuthLogoutRequested>(_onLogout);
    on<AuthSignedUp>((event, emit) => emit(AuthSignedIn(event.account)));
    on<AuthRefreshed>(_onRefreshed);
  }

  final JoopRepository _repository;

  Future<void> _onStarted(AuthStarted event, Emitter<AuthState> emit) async {
    try {
      final account = await _repository.restore();
      emit(account == null ? const AuthSignedOut() : AuthSignedIn(account));
    } on ApiException catch (e) {
      emit(AuthSignedOut(error: e.message));
    }
  }

  Future<void> _onLogin(AuthLoginRequested event, Emitter<AuthState> emit) async {
    emit(const AuthLoading());
    try {
      emit(AuthSignedIn(await _repository.login(event.company.trim(), event.password,
          user: event.user.trim(), server: event.server)));
    } on ApiException catch (e) {
      emit(AuthSignedOut(error: e.message));
    }
  }

  Future<void> _onRefreshed(AuthRefreshed event, Emitter<AuthState> emit) async {
    if (state is! AuthSignedIn) return;
    try {
      final account = await _repository.restore();
      emit(account == null ? const AuthSignedOut() : AuthSignedIn(account));
    } on ApiException {
      // No connection: the words stay in the previous language until the next start.
    }
  }

  Future<void> _onLogout(AuthLogoutRequested event, Emitter<AuthState> emit) async {
    await _repository.logout();
    emit(const AuthSignedOut());
  }
}
